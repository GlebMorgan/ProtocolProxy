import importlib
import threading
from contextlib import contextmanager
from os import listdir, linesep
from os.path import abspath, dirname, isfile, join as joinpath, isdir
from typing import Union

from logger import Logger
from utils import bytewise

from device import Device, DataInvalidError
from notifier import Notifier
from serial_transceiver import (SerialTransceiver, PelengTransceiver, SerialError, SerialCommunicationError,
                                SerialReadTimeoutError, SerialWriteTimeoutError, BadDataError, BadRfcError)

log = Logger("App")
tlog = Logger("Transactions")


class ApplicationError(RuntimeError):
    """ ProtocolProxy application-level error """


class CommandError(ApplicationError):
    """ Invalid command signature / parameters / semantics """


class CommandWarning(ApplicationError):
    """ Abnormal things happened while processing the command """


class ProtocolLoader(dict):
    def __init__(self, basePath: str, folder: str):
        super().__init__()
        self.protocolsPath = joinpath(basePath, folder)
        if not isdir(self.protocolsPath):
            # TODO: catch this error in ui and ask for valid protocols path
            raise ApplicationError("Protocols directory path is invalid")
        self.directory = folder
        for filename in listdir(self.protocolsPath):
            if (filename.endswith('.py') and isfile(joinpath(self.protocolsPath, filename))):
                self[filename[:-3].lower()] = None

    def __getitem__(self, item):
        try:
            protocol = super().__getitem__(item)
        except KeyError:
            raise ApplicationError(f"No such protocol: {item}")
        if protocol is not None:
            return protocol
        else:
            try:
                deviceModule = importlib.import_module('.'.join((self.directory, item)))
            except ModuleNotFoundError:
                raise ApplicationError(f"Cannot find protocol file '{item}.py' in '{self.directory}' directory "
                                       f"(application resources corrupted?)")
            try:
                deviceClass = getattr(deviceModule, item.upper())
            except AttributeError:
                raise ApplicationError(f"Cannot find protocol class {item.upper()} "
                                       f"in '{joinpath(self.directory, item)}.py' "
                                       f"(wrong file in '{self.directory}' directory?)")
            if not issubclass(deviceClass, Device):
                raise ApplicationError(f"Class {item.upper()} in '{joinpath(self.directory, item)}.py' is invalid "
                                       f"(directory '{self.directory}' should contain protocol classes only)")
            self[item] = deviceClass

            return deviceClass


class App(Notifier):
    VERSION: str = '0.2'
    PROJECT_FOLDER: str = dirname(abspath(__file__))
    DEVICES = ProtocolLoader(PROJECT_FOLDER, 'devices')

    log.debug(f"Launched from: {abspath(__file__)}")
    log.info(f"Project directory: {PROJECT_FOLDER}")
    log.info(f"Protocols directory: {joinpath(PROJECT_FOLDER, DEVICES.directory)}")

    class CONFIG:
        INTERFACES: tuple = ('serial', 'ethernet')
        DEFAULT_APP_COM_PORT: str = 'COM11'
        DEFAULT_DEV_COM_PORT: str = 'COM1'
        DEVICE_TIMEOUT: float = 0.5  # sec
        SMALL_TIMEOUT_DELAY: float = 0.5  # sec
        BIG_TIMEOUT_DELAY: int = 5  # sec
        NO_REPLY_HOPELESS: int = 50  # timeouts
        NATIVE_SOFT_COMM_MODE: bool = True

    def __init__(self):
        super().__init__()

        self.cmdThread: threading.Thread = None
        self.commThread: threading.Thread = None
        self.stopCommEvent: threading.Event = None
        self.commRunning: bool = False
        self.loggerLevels = {
            'App': 'DEBUG',
            'Transactions': 'DEBUG',
            'Packets': 'DEBUG',
        }

        self.device: Device = None  # while device is None, comm interfaces are not initialized
        self.interactWithNativeSoft: bool = self.CONFIG.NATIVE_SOFT_COMM_MODE

        # when communication is running, these ▼ attrs should be accessed only from inside commThread!
        self.appInt: SerialTransceiver = None  # serial interface to native communication soft (virtual port)
        self.devInt: PelengTransceiver = None  # serial interface to physical device (real port)
        self.nativeSoftConnEstablished: bool = False
        self.nativeData: bytes = None
        self.deviceData: bytes = None

        self.init()

    def init(self):
        for name, level in self.loggerLevels.items(): Logger.LOGGERS[name].setLevel(level)
        self.cmdThread = threading.Thread(name="CMD thread", target=self.runCmd)
        self.cmdThread.start()

    @contextmanager
    def restartNeeded(self):
        if (not self.commRunning):
            yield
        else:
            self.stop()
            yield
            self.start()

    def getInterface(self, intType: str):
        if intType.lower() == 'virtual serial':
            return SerialTransceiver()
        elif intType.lower() == 'serial':
            return PelengTransceiver(timeout=self.CONFIG.DEVICE_TIMEOUT)
        elif intType.lower() == 'ethernet':
            log.error(f"Interface {intType} is not supported currently")
            return NotImplemented
        else: raise ApplicationError(f"Unknown interface: {intType}")

    def initInterfaces(self):
        self.appInt = self.getInterface('virtual serial')
        self.appInt.port = self.CONFIG.DEFAULT_APP_COM_PORT
        self.devInt = self.getInterface(self.device.COMMUNICATION_INTERFACE)
        self.devInt.port = self.CONFIG.DEFAULT_DEV_COM_PORT
        self.devInt.device = self.device.DEVICE_ADDRESS

    def setProtocol(self, deviceName: str):
        self.device = self.DEVICES[deviceName]()
        if not self.appInt and not self.devInt: self.initInterfaces()
        if self.devInt.INTERFACE_NAME != self.device.COMMUNICATION_INTERFACE:
            log.error("Only serial interface is supported currently. Interface property is ignored.")
        with self.device.lock, self.restartNeeded():
            self.device.configureInterface(self.appInt, self.devInt)

    def start(self):
        if self.commThread:
            log.warning("Communication is already launched — ignoring command")
            return
        if not self.devInt: raise ApplicationError("Target device is not set")
        log.info(f"Starting transactions between {self.device.name} via '{self.devInt.token}' "
                 f"and native control software via '{self.appInt.token}'")
        log.info("Launching communication...")
        self.stopCommEvent = threading.Event()
        self.commThread = threading.Thread(
                name="Communication thread", target=self.commLoop, args=(self.stopCommEvent,))
        self.commThread.start()

    def stop(self):
        if not self.commThread:
            log.warning("Communication is already stopped — ignoring command")
            return
        log.info("Interrupting communication...")
        self.stopCommEvent.set()
        self.commThread.join()
        self.stopCommEvent.clear()
        self.commThread = None

    @contextmanager
    def controlSoftErrorsHandler(self):
        subject = self.device.name
        try:
            yield
        except SerialReadTimeoutError:
            self.appInt.nTimeouts += 1
            if self.appInt.nTimeouts == 1:
                tlog.warning(f"No reply from {subject} native control soft...")
            else:
                tlog.debug(f"No reply from {subject} native control soft [{self.appInt.nTimeouts}]")
        except BadDataError as e:
            tlog.error(f"Received bad data from {subject} native control soft "
                       f"(wrong data source is connected to {self.appInt.token}?)")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        except BadRfcError as e:
            tlog.error(f"Checksum validation failed for packet from {subject} native control soft")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        except DataInvalidError as e:
            tlog.warning(f"Invalid data received from {subject} native control soft (app misoperation?)")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        else:
            if self.appInt.nTimeouts:
                tlog.info(f"Found data from {subject} native control soft after {self.appInt.nTimeouts} timeouts")
                self.appInt.nTimeouts = 0
            if self.nativeSoftConnEstablished is False: self.nativeSoftConnEstablished = True
            return
        finally:
            if self.appInt.in_waiting > self.device.NATIVE_MAX_INPUT_BUFFER_SIZE:
                nBytesUnread = self.appInt.in_waiting
                tlog.error(f"{subject} native control soft input buffer ({self.appInt.port}) is filled over limit")
                self.appInt.reset_input_buffer()
                tlog.info(f"{self.appInt.token}: {nBytesUnread} bytes flushed.")
        tlog.info(f"Using {subject} idle payload: [{bytewise(self.device.IDLE_PAYLOAD)}]")
        self.nativeData = self.device.IDLE_PAYLOAD

    @contextmanager
    def deviceErrorsHandler(self, stopEvent):
        subject = self.device.name
        try:
            yield
        except SerialReadTimeoutError:
            self.devInt.nTimeouts += 1
            if self.devInt.nTimeouts == 1:
                tlog.warning(f"No reply from {subject} device...")
            else:
                tlog.debug(f"No reply from {subject} device [{self.devInt.nTimeouts}]")
            # TODO: redesign this ▼ to set new timer interval to 5x transaction period
            #  when scheduler will be used instead of 'for loop' for triggering transactions
            stopEvent.wait(self.CONFIG.SMALL_TIMEOUT_DELAY if self.devInt.nTimeouts < self.CONFIG.NO_REPLY_HOPELESS
                           else self.CONFIG.BIG_TIMEOUT_DELAY)
        except BadDataError as e:
            tlog.error(f"Received corrupted data from '{subject}' device")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        except BadRfcError as e:
            tlog.error(f"Checksum validation failed for packet from {subject} device")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        except DataInvalidError as e:
            tlog.error(f"Invalid data received from {subject} device")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        else:
            if self.devInt.nTimeouts:
                tlog.info(f"Found data from {subject} device after {self.devInt.nTimeouts} timeouts")
                self.devInt.nTimeouts = 0
            return
        finally:
            if self.devInt.in_waiting > self.device.DEVICE_MAX_INPUT_BUFFER_SIZE:
                tlog.warning(f"{subject} serial input buffer ({self.devInt.port}) comes to overflow")
                self.devInt.reset_input_buffer()
                tlog.info(f"{self.devInt.token}: {self.devInt.in_waiting} bytes flushed.")

    def commLoop(self, stopEvent):
        # TODO: introduce condition objects that will contain state of communication for native control soft and device
        #      Output transactions on demand; initially show state changes only (as well as errors/warnings)
        #      State objects are defined in app, but stored in serial objects
        try:
            with self.appInt, self.devInt:
                try:
                    self.commRunning = True
                    log.info("Communication launched")
                    while True:  # TODO: replace this loop with proper timing-based scheduler
                        self.nativeData = self.deviceData = None
                        if (stopEvent.is_set()):
                            log.info("Received stop communication command.")
                            break
                        with self.device.lock:
                            with self.controlSoftErrorsHandler():
                                if self.interactWithNativeSoft: self.nativeData = self.device.receiveNative(self.appInt)
                                else: self.nativeData = self.device.IDLE_PAYLOAD
                            if self.nativeData is None: continue

                            self.deviceData = self.device.wrap(self.nativeData)
                            try:
                                self.devInt.sendPacket(self.deviceData)
                            except SerialWriteTimeoutError:
                                tlog.error(f"Failed to send data over '{self.devInt.token}' (device disconnected?)")
                                continue  # TODO: what needs to be done when unexpected error happens [2]?

                            with self.deviceErrorsHandler(stopEvent):
                                self.deviceData = self.devInt.receivePacket()
                            if self.deviceData is None: continue

                            self.nativeData = self.device.unwrap(self.deviceData)
                            try:
                                if self.interactWithNativeSoft: self.device.sendNative(self.appInt, self.nativeData)
                            except SerialWriteTimeoutError:
                                if self.nativeSoftConnEstablished is False:  # wait for native control soft to launch
                                    if self.appInt.nTimeouts < 2:
                                        tlog.info(f"Waiting for {self.device.name} native control soft to launch")
                                else:
                                    tlog.error(f"Failed to send data over {self.appInt.token} "
                                               f"(native communication soft disconnected?)")
                                    # TODO: what needs to be done when unexpected error happens [3]?

                            # TODO: self.ui.update()

                except (SerialError, DataInvalidError) as e:
                    tlog.fatal(f"Transaction failed: {e}")
                    tlog.showStackTrace(e, level='debug')
                    # TODO: what needs to be done when unexpected error happens [1]?
                finally:
                    self.appInt.nTimeouts = self.devInt.nTimeouts = 0
                    self.nativeSoftConnEstablished = False
                    self.commRunning = False
                    log.info("Communication stopped")
        except SerialCommunicationError as e:
            log.fatal(f"Failed to start communication: {e}")
            log.showStackTrace(e, level='debug')

    def suppressLoggers(self, mode: Union[str, bool] = None) -> Union[str, bool]:
        isAltered = not all((Logger.LOGGERS[loggerName].levelName == level
                             for loggerName, level in self.loggerLevels.items()))
        if mode is None:
            # ▼ return whether loggers was suppressed (True) or they are as defined in self.loggerLevels (False)
            return isAltered
        if mode == 'kill':  # disable all loggers completely
            for loggerName in self.loggerLevels:
                Logger.LOGGERS[loggerName].disabled = True
            return "————— Transactions logging output disabled —————".center(80)
        elif isAltered:  # enable all loggers back
            for loggerName in self.loggerLevels:
                Logger.LOGGERS[loggerName].disabled = False

        if mode is False or mode == 'False':  # assign levels according to self.loggerLevels
            for loggerName, level in self.loggerLevels.items(): Logger.LOGGERS[loggerName].setLevel(level)
            return "————— Transactions logging output restored —————".center(80)
        elif mode is True or mode == 'True':  # set transactions-related loggers to lower level
            Logger.LOGGERS["Transactions"].setLevel('WARNING')
            Logger.LOGGERS["Packets"].setLevel('ERROR')
            return "————— Transactions logging output suppressed —————".center(80)
        elif mode in Logger.LEVELS:  # set all loggers to given level
            for loggerName in self.loggerLevels: Logger.LOGGERS[loggerName].setLevel(mode)
            return f"————— Transactions logging output set to '{mode}' level —————".center(80)
        else:
            raise ValueError(f"Invalid logging mode '{mode}'")

    @staticmethod
    def setTransactionOutputLevel(level: Union[str, int]):
        tlog.setLevel(level)
        Logger.LOGGERS['Packets'].setLevel(level)

    def runCmd(self):
        cmd = Logger("AppCMD", mode='noFormatting')

        commandsHelp = {
            'h': ("h [command]", "show help"),
            'show': ("show [int|dev|config|app]", "show current state of specified parameter"),
            's': ("s", "start/stop communication"),
            'r': ("r", "restart communication"),
            'com': ("com <in|out> <ComPort_number>", "change internal/device com port"),
            'p': ("p <device_name>", "change protocol"),
            'n': ("n", "enable/disable transactions with native control soft"),
            'so': ("so <mode>", "set transactions output suppression"),
            'e': ("e", "exit app"),
            'd': ("d <parameter_shortcut> [new_value]", "show/set device parameter")
        }

        def showHelp(parameter=None):
            if parameter is None:
                commandsColumnWidth = max(len(desc[0]) for desc in commandsHelp.values())
                lines = []
                for desc in commandsHelp.values():
                    lines.append(f"{desc[0].rjust(commandsColumnWidth)} — {desc[1]}")
                lines.append(f"{'Enter (while communication)'.rjust(commandsColumnWidth)} — "
                             f"{'switch transactions output suppression'}")
                return linesep.join(lines)
            else:
                if (parameter not in commandsHelp):
                    raise CommandError(f"No such command '{command}'")
                return " — ".join(commandsHelp[parameter])

        def castInput(targetType: type, value: str) -> Union[None, str, int, float, bool]:
            value = value.lower()

            if targetType is str:
                return value

            if targetType is bool:
                if value in ('true', 'yes', '1', 'on'): return True
                elif value in ('false', 'no', '0', 'off'): return False

            elif targetType is int:
                try:
                    if (value[:2] == '0x'): return int(value, 16)
                    elif (value[:2] == '0b'): return int(value, 2)
                    else: return int(value)
                except ValueError: pass  # Value error will be raised at the end of function

            elif targetType is float:
                try:
                    return float(value)
                except ValueError: pass  # Again, value error will be raised below

            raise ValueError(f"Cannot convert '{value}' to {targetType}")

        print()
        cmd.info(f"————— Protocol proxy v{self.VERSION} CMD interface —————".center(80))
        print()
        cmd.info(showHelp())
        print()
        cmd.info(f"Available protocols: {', '.join(self.DEVICES)}")

        while True:
            try:
                userinput = input('--> ')
                if (userinput.strip() == ''):
                    if self.commRunning:
                        if not self.suppressLoggers():
                            cmd.info(self.suppressLoggers('FATAL'))
                        else:
                            cmd.info(self.suppressLoggers(False))
                    continue
                params = userinput.strip().split()
                command = params[0]

                if (command == 'e'):
                    if self.commRunning:
                        self.stopCommEvent.set()
                        self.commThread.join()
                    cmd.error("Terminated :)")  # 'error' is just for visual standing out
                    import sys
                    sys.exit(0)

                elif command in ('h', 'help'):
                    if len(params) == 1:
                        cmd.info(showHelp())
                    else:
                        cmd.info(showHelp(params[1]))

                elif command in ('sh', 'show'):
                    if len(params) < 2:
                        raise CommandError("Specify parameter to show")
                    elem = params[1]
                    if elem in ('com', 'int', 'comm'):
                        cmd.info(f"Device interface: {self.devInt}")
                        cmd.info(f"Control soft interface: {self.appInt}")
                    elif elem in ('d', 'dev', 'device', 'p', 'protocol'):
                        cmd.info(self.device)
                    elif elem in ('par', 'params'):
                        cmd.info(self.device.params)
                    elif elem in ('conf', 'config'):
                        for par in self.CONFIG.__dict__:
                            if par == par.strip('__'):
                                cmd.info(f"{par} = {getattr(self.CONFIG, par)}")
                    elif elem in ('this', 'self', 'app', 'state'):
                        cmd.info(NotImplemented)
                    else: raise CommandError(f"No such parameter '{elem}'")

                elif not self.device and command != 'p':
                    raise CommandError("Target device is not defined. Define with 'p <deviceName>'")

                elif command == 's':
                    if self.commRunning:
                        self.stop()
                        if self.suppressLoggers():
                            cmd.info(self.suppressLoggers(False))
                    else:
                        self.start()

                elif command == 'r':
                    if self.commRunning:
                        self.stop()
                        if self.suppressLoggers():
                            cmd.info(self.suppressLoggers(False))
                        self.start()
                    else: cmd.info("Cannot restart communication — not running currently")

                elif command in ('n', 'native'):
                    self.interactWithNativeSoft = not self.interactWithNativeSoft
                    cmd.info(f"{'Enabled' if self.interactWithNativeSoft else 'Disabled'} "
                             f"interaction with {self.device.name} native control soft")

                elif command == 'com':
                    if len(params) < 3:
                        raise CommandError("Specify <target com port> and <new port number>")
                    if self.commRunning:
                        raise ApplicationError("Cannot change port number when communication is running")
                    direction = params[1]
                    newPortNumber = params[2].strip('0')
                    if direction.lower() not in ('in', 'out'):
                        raise CommandError("Com port specification is invalid. Expected [in|out]")
                    if not newPortNumber.isdecimal():
                        raise CommandError("New port number is invalid. Integer expected")
                    if len(newPortNumber) > 2:
                        raise CommandError("That's definitely invalid port number!")
                    if newPortNumber in (intf.port.upper().strip('COM') for intf in (self.devInt, self.appInt)):
                        raise ApplicationError(f"Port number {newPortNumber} is already assigned to serial interface")
                    interface = self.appInt if direction == 'in' else self.devInt
                    interface.port = 'COM' + newPortNumber
                    cmd.info(f"'{direction.capitalize()}' COM port changed to {interface.port}")

                elif command == 'p':
                    if len(params) < 2:
                        raise CommandError("Specify new device name")
                    newDeviceName = params[1].lower()
                    if newDeviceName not in self.DEVICES:
                        raise CommandError(f"No such device: '{newDeviceName}'")
                    self.setProtocol(newDeviceName)

                elif command == 'd':
                    if len(params) == 1:
                        cmd.info(NotImplemented)
                    else:
                        parAlias = params[1]
                        if (parAlias not in self.device.API):
                            raise CommandError(f"{self.device.name} has no parameter with shortcut '{parAlias}'")
                        par = self.device.API[parAlias]
                        if len(params) == 2:
                            # ▼ show parameter value
                            cmd.info(par)
                        else:
                            # ▼ set parameter value
                            newValue = params[2]
                            if par not in self.device.params:
                                raise CommandError(f"{self.device.name}.{par.name} is a property "
                                                   f"and cannot be changed externally")
                            try: par.__set__(self.device, castInput(par.type, newValue))
                            except ValueError as e: raise CommandError(e)
                            cmd.info(par)


                elif command in ('so', 'supp', 'sl'):
                    if not self.commRunning:
                        raise CommandError(f"Output suppression is used only while communication is running")
                    if len(params) < 2:
                        raise CommandError("Specify suppression mode")
                    suppressionMode = params[1]
                    try:
                        self.suppressLoggers(suppressionMode)
                    except ValueError as e:
                        raise ApplicationError(e)

                else: raise CommandError(f"Wrong command '{command}'")

            except ApplicationError as e: cmd.showError(e)
            except SerialCommunicationError as e: cmd.showError(e)
            except Exception as e: cmd.showStackTrace(e)


if __name__ == '__main__':
    Logger.LOGGERS["Device"].setLevel("INFO")
    App()
