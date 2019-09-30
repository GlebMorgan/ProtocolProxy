import importlib
import threading
import readline
from contextlib import contextmanager
from itertools import chain
from os import listdir, linesep
from os.path import abspath, dirname, isfile, join as joinpath, isdir, expandvars as envar, basename
from sys import exit as sys_exit, path as sys_path
from typing import Union, Dict, Type

from Utils import Logger, bytewise, castStr, ConfigLoader, formatDict

from device import Device, DataInvalidError
from notifier import Notifier
from Transceiver import SerialTransceiver, PelengTransceiver
from Transceiver.errors import *

log = Logger("App")
tlog = Logger("Transactions")


class ApplicationError(RuntimeError):
    """ ProtocolProxy application-level error """
    __slots__ = ()


class CommandError(ApplicationError):
    """ Invalid command signature / parameters / semantics """
    __slots__ = ()


class CommandWarning(ApplicationError):
    """ Abnormal things happened while processing the command """
    __slots__ = ()


class ProtocolLoader(dict):
    path: str = joinpath(envar('%APPDATA%'), '.PelengTools', 'ProtocolProxy', 'devices')

    def __init__(self, path: str = None):
        super().__init__()
        if path is None:
            self.__protocols_path__ = self.__class__.path
        else:
            if not isdir(path): raise ApplicationError(f"Invalid protocols directory path: {path}")
            else: self.__protocols_path__ = path
        for filename in listdir(self.__protocols_path__):
            if (filename.endswith('.py') and isfile(joinpath(self.__protocols_path__, filename))):
                self.setdefault(filename[:-3].lower())
        sys_path.append(self.__protocols_path__)

    def __getitem__(self, item) -> Type[Device]:
        pDir = basename(self.__protocols_path__)

        try:
            protocol = super().__getitem__(item)
        except KeyError:
            raise ApplicationError(f"No such protocol: {item}")

        if protocol is not None:
            return protocol
        else:
            try:
                deviceModule = importlib.import_module(item)
            except ModuleNotFoundError:
                raise ApplicationError(f"Cannot find protocol file '{item}.py' in '{pDir}' directory "
                                       f"(application resources corrupted?)")
            try:
                deviceClass = getattr(deviceModule, item.upper())
            except AttributeError:
                raise ApplicationError(f"Cannot find protocol class {item.upper()} "
                                       f"in '{joinpath(pDir, item)}.py' "
                                       f"(wrong file in '{pDir}' directory?)")
            if not issubclass(deviceClass, Device):
                raise ApplicationError(f"Class {item.upper()} in '{joinpath(pDir, item)}.py' is invalid "
                                       f"(directory '{pDir}' should contain protocol classes only)")
            self[item] = deviceClass

            return deviceClass


class CONFIG(ConfigLoader, section='APP'):
    DEVICES_FOLDER_REL: str = 'devices'
    DEFAULT_APP_COM_PORT: str = 'COM11'
    DEFAULT_DEV_COM_PORT: str = 'COM1'
    DEVICE_TIMEOUT: float = 0.5  # sec
    SMALL_TIMEOUT_DELAY: float = 0.5  # sec
    BIG_TIMEOUT_DELAY: int = 5  # sec
    NO_REPLY_HOPELESS: int = 50  # timeouts
    NATIVE_SOFT_COMM: bool = True


class App(Notifier):
    VERSION: str = '1.0.dev0'  # TEMP: move to main.py
    PROJECT_NAME = 'ProtocolProxy'  # TEMP: move to main.py
    PROJECT_FOLDER: str = dirname(abspath(__file__))  # TEMP: move to main.py
    protocols: Dict[str, Type[Device]] = None

    # API methods:
    #   • init()
    #   • startCmdThread()
    #   • setProtocol
    #   • start()
    #   • stop()
    #
    # API objects:
    #   • device
    #   • CONFIG

    def __init__(self):
        super().__init__()
        CONFIG.load()

        self.protocols: ProtocolLoader = ProtocolLoader()

        self.cmdThread: threading.Thread = None
        self.commThread: threading.Thread = None
        self.stopCommEvent: threading.Event = None
        self.commRunning: bool = False

        self.loggerLevels = {
            'App': 'DEBUG',
            'Transactions': 'DEBUG',
            'Packets': 'DEBUG',
            'Device': 'INFO',
            'Config': 'INFO',
        }

        self.device: Device = None  # while device is None, comm interfaces are not initialized
        self.interactWithNativeSoft: bool = CONFIG.NATIVE_SOFT_COMM

        # when communication is running, these ▼ attrs should be accessed only from inside commThread!
        self.appInt: SerialTransceiver = None  # serial interface to native communication soft (virtual port)
        self.devInt: PelengTransceiver = None  # serial interface to physical device (real port)
        self.nativeSoftConnEstablished: bool = False
        self.nativeData: bytes = None
        self.deviceData: bytes = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.commThread:
            if self.commRunning:
                self.stopCommEvent.set()
            self.commThread.join()

        if self.cmdThread:
            self.cmdThread.join()

        CONFIG.save()
        print("TERMINATED :)")

    def init(self):
        log.debug(f"Launched from:      {abspath(__file__)}")  # TEMP
        log.info(f"Project directory:   {self.PROJECT_FOLDER}")
        log.info(f"Protocols directory: {joinpath(self.protocols.__protocols_path__)}")
        for name, level in self.loggerLevels.items(): Logger.LOGGERS[name].setLevel(level)

    def startCmdThread(self):
        self.cmdThread = threading.Thread(name="CMD thread", target=self.runCmd)
        self.cmdThread.start()

    @contextmanager
    def restartNeeded(self):
        if not self.commRunning:
            yield
        else:
            self.stop()
            yield
            self.start()

    @staticmethod
    def getInterface(intType: str):
        if intType.lower() == 'virtual serial':
            return SerialTransceiver()
        elif intType.lower() == 'serial':
            return PelengTransceiver()
        elif intType.lower() == 'ethernet':
            raise NotImplementedError(f"Interface {intType} is not supported currently")
        else: raise ApplicationError(f"Unknown interface: {intType}")

    def initInterfaces(self):
        self.appInt = SerialTransceiver()
        self.appInt.port = CONFIG.DEFAULT_APP_COM_PORT
        self.devInt = self.getInterface(self.device.COMMUNICATION_INTERFACE)
        self.devInt.port = CONFIG.DEFAULT_DEV_COM_PORT
        # self.devInt.device = self.device.DEV_ADDRESS  # TESTME: what was the reason of this line here???

    def setProtocol(self, deviceName: str):
        self.device = self.protocols[deviceName]()
        if not self.appInt and not self.devInt: self.initInterfaces()
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
        except BadCrcError as e:
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
            if self.appInt.in_waiting > self.device.APP_MAX_INPUT_BUFFER_SIZE:
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
            stopEvent.wait(CONFIG.SMALL_TIMEOUT_DELAY if self.devInt.nTimeouts < CONFIG.NO_REPLY_HOPELESS
                           else CONFIG.BIG_TIMEOUT_DELAY)
        except BadDataError as e:
            tlog.error(f"Received corrupted data from '{subject}' device")
            tlog.info("Packet discarded")
            tlog.showError(e, level='debug')
        except BadCrcError as e:
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
            if self.devInt.in_waiting > self.device.DEV_MAX_INPUT_BUFFER_SIZE:
                tlog.warning(f"{subject} serial input buffer ({self.devInt.port}) comes to overflow")
                self.devInt.reset_input_buffer()
                tlog.info(f"{self.devInt.token}: {self.devInt.in_waiting} bytes flushed.")

    def commLoop(self, stopEvent):
        try:
            with self.appInt, self.devInt:
                try:
                    self.commRunning = True
                    self.nativeSoftConnEstablished = False
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

                            self.nativeData = self.device.wrap(self.nativeData)
                            try:
                                self.devInt.sendPacket(self.nativeData)
                            except SerialWriteTimeoutError:
                                tlog.error(f"Failed to send data over '{self.devInt.token}' (device disconnected?)")
                                continue  # TODO: what needs to be done when unexpected error happens [2]?

                            with self.deviceErrorsHandler(stopEvent):
                                self.deviceData = self.devInt.receivePacket()
                            if self.deviceData is None: continue

                            self.deviceData = self.device.unwrap(self.deviceData)
                            try:
                                if self.interactWithNativeSoft and self.appInt.nTimeouts == 0:  # duck-tape-ish...
                                    self.device.sendNative(self.appInt, self.deviceData)
                            except SerialWriteTimeoutError:
                                if self.nativeSoftConnEstablished is False:  # wait for native control soft to launch
                                    if self.appInt.nTimeouts < 2:
                                        tlog.info(f"Waiting for {self.device.name} native control soft to launch")
                                else:
                                    tlog.error(f"Failed to send data over {self.appInt.token} "
                                               f"(native communication soft disconnected?)")
                                    # TODO: what needs to be done when unexpected error happens [3]?

                            # TODO: self.triggerEvent(ui_update)

                except (SerialError, DataInvalidError) as e:
                    tlog.fatal(f"Transaction failed: {e}")
                    tlog.showStackTrace(e, level='debug')
                    # TODO: what needs to be done when unexpected error happens [1]?
                finally:
                    self.appInt.nTimeouts = self.devInt.nTimeouts = 0
                    self.commRunning = False
                    log.info("Communication stopped")
        except SerialError as e:
            log.fatal(f"Failed to start communication: {e}")
            log.showStackTrace(e, level='debug')
        finally:
            self.commThread = None

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
            for loggerName in self.loggerLevels: Logger.LOGGERS[loggerName].setLevel('ERROR')
            Logger.LOGGERS["Transactions"].setLevel('WARNING')
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
            'show': ("show [int|dev|config|app|log]", "show current state of specified parameter"),
            's': ("s", "start/stop communication"),
            'r': ("r", "restart communication"),
            'com': ("com [<in|out> <new_COM_port_number>]", "change internal/device com port"),
            'p': ("p <device_name>", "change protocol"),
            'n': ("n", "enable/disable transactions with native control soft"),
            'so': ("so <mode>", "set transactions output suppression"),
            'e': ("e", "exit app"),
            'd': ("d <parameter_shortcut> [new_value]", "show/set device parameter"),
            'log': ("log [<logger_name>, <new_level>]", "set logging level to specified logger"),
            '>': ("> <executable_python_expression>", "execute arbitrary Python statement "
                                                      "(use 'self' to access application attrs)"),
        }

        def showHelp(parameter=None):
            if parameter == '': return ''
            elif parameter is None:
                commandsColumnWidth = max(len(desc[0]) for desc in commandsHelp.values())
                lines = []
                for desc in commandsHelp.values():
                    lines.append(f"{desc[0].rjust(commandsColumnWidth)} — {desc[1]}")
                lines.append(f"{'Enter (while communication)'.rjust(commandsColumnWidth)} — "
                             f"{'switch transactions output suppression'}")
                return linesep.join(lines)
            else:
                if (parameter not in commandsHelp):
                    raise CommandError(f"No such command '{parameter}'")
                return " — ".join(commandsHelp[parameter])

        def test(*args):
            cmd.debug("Test function output. Args: " + (', '.join(args) if args else '<None>'))
            if not args:
                cmd.error("No parameters — nothing to do")
                return
            elif (args[0] == 'MOSSim'):
                self.device.IDLE_PAYLOAD = bytes.fromhex('85 43 00 04 00 04 00 00 00 00')
                cmd.debug(f"{self.device.name} default payload changed to [{bytewise(self.device.IDLE_PAYLOAD)}]")
            elif args[0] == 'NCS':
                self.device.IDLE_PAYLOAD = bytes.fromhex('00 01 00 00 00 00 00 00 29 01 00 00')
                cmd.debug(f"{self.device.name} default payload changed to [{bytewise(self.device.IDLE_PAYLOAD)}]")
            elif args[0] == 'Default':
                self.device.IDLE_PAYLOAD = bytes.fromhex('00 01 01 00 00 00 00 00 00 00 00 00')
                cmd.debug(f"{self.device.name} default payload changed to [{bytewise(self.device.IDLE_PAYLOAD)}]")
            elif args[0] == 'config':
                print(f"BIG_TIMEOUT_DELAY = {CONFIG.BIG_TIMEOUT_DELAY}")
            elif args[0] == 'alterconfig':
                CONFIG.BIG_TIMEOUT_DELAY = 100500  # :D
                print(f"CONFIG.BIG_TIMEOUT_DELAY changed to {CONFIG.BIG_TIMEOUT_DELAY}")
            elif args[0] == 'revertconfig':
                CONFIG.revert()
                print("CONFIG.revert() called")
            else:
                cmd.error(f"No such option defined: {args[0]}")
                return


        print()
        cmd.info(f"————— Protocol proxy v{self.VERSION} CMD interface —————".center(80))
        print()
        cmd.info(showHelp())
        print()
        cmd.info(f"Available protocols: {', '.join(self.protocols)}")

        while True:
            try:
                prompt = '——► ' if self.commRunning else '——> '
                userinput = input(prompt)

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
                    cmd.error("Terminating...")  # 'error' is just for visual standing out
                    # self.notify('quit')  #FIXME Says 'non-existing event'
                    sys_exit(0)

                elif command in ('h', 'help'):
                    if len(params) == 1:
                        cmd.info(showHelp())
                    else:
                        cmd.info(showHelp(params[1]))

                elif command in ('t', 'test'):
                    test(*params[1:])

                elif command in ('sh', 'show'):
                    if len(params) < 2:
                        raise CommandError("Specify parameter to show")
                    elem = params[1]
                    if elem in ('i', 'int', 'c', 'com', 'comm'):
                        cmd.info(f"Device interface: {self.devInt}")
                        cmd.info(f"Control soft interface: {self.appInt}")
                    elif elem in ('d', 'dev', 'device', 'p', 'protocol'):
                        if not self.device: cmd.info("Device is not selected")
                        else:
                            baseClass = self.device.__class__.__bases__[0]
                            for attrName in baseClass.__annotations__:
                                if attrName.isupper() and hasattr(self.device, attrName):
                                    attr = getattr(self.device, attrName)
                                    if (isinstance(attr, bytes)):
                                        attr = f'[{bytewise(attr)}]'
                                    elif (isinstance(attr, dict)):
                                        attr = formatDict(attr)
                                    cmd.info(f"{self.device.name}.{attrName} = {attr}")
                    elif elem in ('par', 'params'):
                        cmd.info(self.device.params)
                    elif elem in ('conf', 'config'):
                        for par in CONFIG.params():
                            if par == par.strip('__'):
                                cmd.info(f"{par} = {getattr(CONFIG, par)}")
                    elif elem in ('this', 'self', 'app', 'state'):
                        cmd.info(NotImplemented)
                    elif elem in ('l', 'log'):
                        cmd.info(', '.join(f"{logName} = {level}" for logName, level in self.loggerLevels.items()))
                    elif elem in ('e', 'events'):
                        handlersDict = {e:[h.__name__ for h in handlers] for e, handlers in Notifier.events.items()}
                        cmd.info(f"Event handlers: {formatDict(handlersDict)}")
                    else: raise CommandError(f"No such parameter '{elem}'")

                elif command in ('l', 'log'):
                    if len(params) == 1:
                        cmd.info(', '.join(f"{logName} = {level}" for logName, level in self.loggerLevels.items()))
                    elif len(params) == 3:
                        loggerName = params[1].capitalize()
                        if (loggerName not in self.loggerLevels):
                            raise CommandError("Invalid logger name. List available loggers via 'sh log'")
                        newLevelName = params[2].upper()
                        if (newLevelName in Logger.LEVELS_SHORT):
                            newLevelName = Logger.LEVELS_SHORT[newLevelName]
                        elif (newLevelName not in Logger.LEVELS):
                            raise CommandError('Invalid logging level')
                        self.loggerLevels[loggerName] = newLevelName
                        Logger.LOGGERS[loggerName].setLevel(newLevelName)
                    else: raise CommandError(f"Wrong parameters")

                elif command == '>':
                    try: print(exec(userinput[2:]))
                    except Exception as e: cmd.error(f"Execution error: {e}")

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
                    if len(params) == 1:
                        cmd.info(f"Device interface: {self.devInt.format()}")
                        cmd.info(f"Control soft interface: {self.appInt.format()}")
                    elif len(params) == 3:
                        if self.commRunning:
                            raise ApplicationError("Cannot change port number when communication is running")
                        direction = params[1]
                        newPortNum = params[2].lstrip('0')
                        if direction.lower() not in ('in', 'out'):
                            raise CommandError("Com port specification is invalid. Expected [in|out]")
                        if not newPortNum.isdecimal():
                            raise CommandError("New port number is invalid. Integer expected")
                        if len(newPortNum) > 2:
                            raise CommandError("That's definitely invalid port number!")
                        if newPortNum in (intf.port.upper().strip('COM') for intf in (self.devInt, self.appInt)):
                            raise ApplicationError(f"Port number {newPortNum} is already assigned to serial interface")
                        interface = self.appInt if direction == 'in' else self.devInt
                        interface.port = 'COM' + newPortNum
                        cmd.info(f"'{direction.capitalize()}' COM port changed to {interface.port}")
                    else: raise CommandError("Wrong parameters")

                elif command == 'p':
                    if len(params) < 2:
                        raise CommandError("Specify new device name")
                    newDeviceName = params[1].lower()
                    if newDeviceName not in self.protocols:
                        raise CommandError(f"No such device: '{newDeviceName}'")
                    self.setProtocol(newDeviceName)

                elif command == 'd':
                    if len(params) == 1:
                        cmd.info(self.device)
                    else:
                        parAlias = params[1]
                        if (parAlias not in self.device.API):
                            raise CommandError(f"{self.device.name} has no parameter with shortcut '{parAlias}'")
                        par = self.device.API[parAlias]
                        if len(params) == 2:
                            # ▼ show parameter value
                            cmd.info(f"{self.device.name}.{par}")
                        else:
                            # ▼ set parameter value
                            newValue = params[2]
                            if par not in self.device.params:
                                raise CommandError(f"{self.device.name}.{par.name} is a property "
                                                   f"and cannot be changed externally")
                            try: par.__set__(self.device, castStr(par.type, newValue))
                            except ValueError as e: raise CommandError(e)
                            cmd.info(f"{self.device.name}.{par}")

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

            except CommandError as e: cmd.showError(e)
            except ApplicationError as e: cmd.showError(e)
            except NotImplementedError as e: cmd.showError(e)
            except SerialCommunicationError as e: cmd.showError(e)
            except Exception as e: cmd.showStackTrace(e)


if __name__ == '__main__':
    from shutil import copyfile

    Logger.LOGGERS["Device"].setLevel("INFO")
    Logger.LOGGERS["Config"].setLevel("DEBUG")
    ConfigLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy')
    ProtocolLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy', 'devices')

    copyfile(joinpath(dirname(abspath(__file__)), 'devices_working', 'sony.py'),
             joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy\\devices', 'sony.py'))
    copyfile(joinpath(dirname(abspath(__file__)), 'devices_working', 'mwxc.py'),
             joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy\\devices', 'mwxc.py'))

    with App() as app:
        app.init()
        app.startCmdThread()
