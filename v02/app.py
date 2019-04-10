import importlib
import threading
from contextlib import contextmanager
from os import listdir, linesep
from os.path import abspath, dirname, isfile, join as joinpath

from logger import Logger
from utils import legacy, bytewise

from device import Device, DataInvalidError
from notifier import Notifier
from serial_transceiver import (SerialTransceiver, PelengTransceiver,
    SerialError, SerialReadTimeoutError, SerialWriteTimeoutError, BadDataError, BadRfcError)

log = Logger("App")


class ApplicationError(RuntimeError):
    """ ProtocolProxy application-level error """


class CommandError(ApplicationError):
    """ Invalid command signature / parameters / semantics """


class CommandWarning(ApplicationError):
    """ Abnormal things happened while processing the command """


class ProtocolLoader(dict):
    def __init__(self, basePath, folder: str):
        super().__init__()
        self.protocolsPath = joinpath(basePath, folder)
        # TODO: verify path exists and valid, else ask for valid one
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
    VERSION = '0.2'
    PROJECT_FOLDER = dirname(abspath(__file__))
    DEVICES = ProtocolLoader(PROJECT_FOLDER, 'devices')

    log.debug(f"Launched from: {abspath(__file__)}")
    log.info(f"Project directory: {PROJECT_FOLDER}")
    log.info(f"Protocols directory: {joinpath(PROJECT_FOLDER, DEVICES.directory)}")

    class CONFIG:
        INTERFACES = ('serial', 'ethernet')
        DEFAULT_APP_COM_PORT = 'COM11'
        DEFAULT_DEV_COM_PORT = 'COM1'
        # TODO: make separate timeouts for device and control soft and make latter almost zero
        SMALL_TIMEOUT_DELAY = 0.1  # sec
        BIG_TIMEOUT_DELAY = 5  # sec
        NO_REPLY_HOPELESS = 10  # timeouts
        NATIVE_SOFT_COMM_MODE = True

    def __init__(self):
        super().__init__()

        self.cmdThread: threading.Thread = None
        self.commThread: threading.Thread = None
        self.stopCommEvent: threading.Event = None
        self.commRunning: bool = False

        self.device: Device = None  # while device is None, comm interfaces are not initialized
        self.interactWithNativeSoft: bool = self.CONFIG.NATIVE_SOFT_COMM_MODE

        # when communication is running, these ▼ attrs should be accessed only from inside commThread!
        self.appInt: SerialTransceiver = None  # serial interface to native communication soft (virtual port)
        self.devInt: PelengTransceiver = None  # serial interface to physical device (real port)
        self.nativeSoftConnEstablished = False
        self.nativeData: bytes = None
        self.deviceData: bytes = None

        self.init()

    def init(self):
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

    @staticmethod
    def getInterface(intType):
        if intType.lower() == 'virtual serial':
            return SerialTransceiver()
        elif intType.lower() == 'serial':
            return PelengTransceiver()
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

    def setProtocol(self, deviceName):
        self.device = self.DEVICES[deviceName]()
        if not self.appInt and not self.devInt: self.initInterfaces()
        if self.devInt.INTERFACE_NAME != self.device.COMMUNICATION_INTERFACE:
            log.error("Only serial interface is supported currently. Interface property is ignored.")
        with self.device.lock, self.restartNeeded():
            self.device.configureInterface(self.appInt, self.devInt)

    def start(self):
        if not self.devInt: raise ApplicationError("Target device is not set")
        log.info(f"Starting transactions between {self.device.name} via '{self.devInt.token}' "
                 f"and native control software via '{self.appInt.token}'")
        log.info("Launching communication...")
        self.stopCommEvent = threading.Event()
        self.commThread = threading.Thread(
                name="Communication thread", target=self.commLoop, args=(self.stopCommEvent,))
        self.commThread.start()

    def stop(self):
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
                log.warning(f"No reply from {subject} native control soft...")
            else:
                log.debug(f"No reply from {subject} native control soft [{self.appInt.nTimeouts}]")
        except BadDataError as e:
            log.error(f"Received bad data from {subject} native control soft "
                      f"(wrong data source is connected to {self.appInt.token}?)")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        except BadRfcError as e:
            log.error(f"Checksum validation failed for packet from {subject} native control soft")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        except DataInvalidError as e:
            log.warning(f"Invalid data received from {subject} native control soft (app misoperation?)")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        else:
            if self.appInt.nTimeouts:
                log.info(f"Found data from {subject} native control soft after {self.appInt.nTimeouts} timeouts")
                self.appInt.nTimeouts = 0
            if self.nativeSoftConnEstablished is False: self.nativeSoftConnEstablished = True
            return
        log.info(f"Using {subject} idle payload: [{bytewise(self.device.IDLE_PAYLOAD)}]")
        self.nativeData = self.device.IDLE_PAYLOAD

    @contextmanager
    def deviceErrorsHandler(self, stopEvent):
        subject = self.device.name
        try:
            yield
        except SerialReadTimeoutError:
            self.devInt.nTimeouts += 1
            if self.devInt.nTimeouts == 1:
                log.warning(f"No reply from {subject} device...")
            else:
                log.debug(f"No reply from {subject} device [{self.devInt.nTimeouts}]")
            # TODO: redesign this ▼ to set new timer interval to 5x transaction period
            #  when scheduler will be used instead of 'for loop' for triggering transactions
            stopEvent.wait(self.CONFIG.SMALL_TIMEOUT_DELAY if self.devInt.nTimeouts < self.CONFIG.NO_REPLY_HOPELESS
                           else self.CONFIG.BIG_TIMEOUT_DELAY)
        except BadDataError as e:
            log.error(f"Received corrupted data from '{subject}' device")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        except BadRfcError as e:
            log.error(f"Checksum validation failed for packet from {subject} device")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        except DataInvalidError as e:
            log.error(f"Invalid data received from {subject} device")
            log.info("Packet discarded")
            log.showError(e, level='debug')
        else:
            if self.devInt.nTimeouts:
                log.info(f"Found data from {subject} device after {self.devInt.nTimeouts} timeouts")
                self.devInt.nTimeouts = 0
            return

    def commLoop(self, stopEvent):
        #TODO: introduce condition objects that will contain state of communication for native control soft and device
        #      Output transactions on demand; initially show state changes only (as well as errors/warnings)
        #      State objects are defined in app, but stored in serial objects
        # FIXME: flush buffer if too many bytes are left in a datastream (to prevent overflow)
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
                        except SerialWriteTimeoutError as e:
                            log.fatal(f"Failed to send data over '{self.devInt.token}' (device disconnected?)")
                            log.showStackTrace(e, level='debug')
                            break  # TODO: what needs to be done when unexpected error happens [2]?

                        with self.deviceErrorsHandler(stopEvent):
                            self.deviceData = self.devInt.receivePacket()
                        if self.deviceData is None: continue

                        self.nativeData = self.device.unwrap(self.deviceData)
                        try:
                            if self.interactWithNativeSoft: self.device.sendNative(self.appInt, self.nativeData)
                        except SerialWriteTimeoutError as e:
                            if self.nativeSoftConnEstablished is False:  # wait for native control soft to launch
                                if self.appInt.nTimeouts < 2:
                                    log.info(f"Waiting for {self.device.name} native control soft to launch")
                            else:
                                log.fatal(f"Failed to send data over {self.appInt.token} "
                                          f"(native communication soft disconnected?)")
                                log.showStackTrace(e, level='debug')
                                break  # TODO: what needs to be done when unexpected error happens [3]?

                        # TODO: self.ui.update()

            except SerialError as e:
                log.fatal(f"Transaction failed: {e}")
                log.showStackTrace(e, level='debug')
                # TODO: what needs to be done when unexpected error happens [1]?
            finally:
                self.appInt.nTimeouts = self.devInt.nTimeouts = 0
                self.nativeSoftConnEstablished = False
                self.commRunning = False
                log.info("Communication stopped")

    @legacy
    def old_commLoop(self, stopEvent):
        with self.appInt, self.devInt:
            name = self.device.name
            nNoDataNative = 0
            nNoDataDevice = 0
            log.info("Communication launched")
            try:
                while True:  # TODO: replace this loop with proper timing-based scheduler
                    if (stopEvent.is_set()):
                        log.info("Received stop communication command.")
                        break
                    with self.device.lock:
                        try:
                            data = self.device.receiveNative(
                                self.appInt) if self.interactWithNativeSoft else self.device.DEFAULT_PAYLOAD
                        except SerialReadTimeoutError:
                            log.warning(f"No reply from {name} native control soft...")
                            log.info("Using default payload")
                            data = self.device.DEFAULT_PAYLOAD
                            nNoDataNative += 1
                        except DataInvalidError as e:
                            log.warning(f"Invalid data received from '{name}' native control soft (app "
                                        f"misoperation or wrong data source is connected to '{self.appInt.token}')")
                            log.info("Using default payload")
                            log.showError(e, level='debug')
                            data = self.device.DEFAULT_PAYLOAD
                        except BadDataError as e:
                            log.error(f"Received corrupted data from '{name}' native control soft")
                            log.info("Packet discarded")
                            log.showError(e, level='debug')
                            continue
                        except BadRfcError as e:
                            log.error(f"Checksum validation failed for packet from "
                                      f"'{name}' native control soft")
                            log.info("Packet discarded")
                            log.showError(e, level='debug')
                            continue
                        else:
                            if nNoDataNative:
                                log.info(f"Found data from '{name}' native control soft after {nNoDataNative} timeouts")
                                nNoDataNative = 0
                        try:
                            self.devInt.sendPacket(self.device.wrap(data))
                        except SerialWriteTimeoutError:
                            log.fatal(f"Failed to send data over '{self.devInt.token}' (device disconnected?)")
                            break
                            # TODO: what needs to be done when unexpected error happens [2]?
                        try:
                            reply = self.devInt.receivePacket()
                        except SerialReadTimeoutError:
                            nNoDataDevice += 1
                            log.error(f"No reply from '{name}' device...")
                            # TODO: redesign this ▼ to set new timer interval to 5x transaction period
                            #  when scheduler will be used instead of 'for loop' for triggering transactions
                            stopEvent.wait(
                                    self.CONFIG.SMALL_TIMEOUT_DELAY if nNoDataDevice < self.CONFIG.NO_REPLY_HOPELESS
                                    else self.CONFIG.BIG_TIMEOUT_DELAY)
                            continue
                        except BadDataError as e:
                            log.error(f"Received corrupted data from '{name}' device")
                            log.info("Packet discarded")
                            log.showError(e, level='debug')
                            continue
                        except BadRfcError as e:
                            log.error(f"Checksum validation failed for packet from '{name}' device")
                            log.info("Packet discarded")
                            log.showError(e, level='debug')
                            continue
                        except DataInvalidError as e:
                            log.error(f"Invalid data received from '{name}' device")
                            log.info("Packet discarded")
                            log.showError(e, level='debug')
                            continue
                        else:
                            if nNoDataDevice:
                                log.info(f"Found data from '{name}' device after {nNoDataDevice} timeouts")
                                nNoDataDevice = 0
                        try:
                            self.device.sendNative(self.appInt, self.device.unwrap(reply))
                        except SerialWriteTimeoutError:
                            log.fatal(f"Failed to send data over '{self.devInt.token}' "
                                      f"(native communication soft is not running?)")
                            break
                            # TODO: what needs to be done when unexpected error happens [3]?

                        # TODO: self.ui.update()
            except SerialError as e:
                log.fatal(f"Transaction failed: {e}")
                log.showStackTrace(e, level='debug')
                # TODO: what needs to be done when unexpected error happens [1]?
            finally:
                # FIXME: tell app that communication is not running any more
                log.info("Communication stopped")

    def runCmd(self):
        # FIXME: suppress output to enter commands
        cmd = Logger("AppCMD", mode='noFormatting')

        commandsHelp = {
            'h':    ("h [command]", "show help"),
            'show': ("show [int|dev|config|app]", "show current state of specified parameter"),
            's':    ("s", "start/stop communication"),
            'com':  ("com <in|out> <ComPort_number>", "change internal/device com port"),
            'p':    ("p <device_name>", "change protocol"),
            'n':    ("n", "enable/disable transactions with native control soft")
        }

        cmd.info(linesep * 3)
        cmd.info(f"——— Protocol proxy v{self.VERSION} CMD interface ———".center(80))
        cmd.info(f"Available protocols: {', '.join(self.DEVICES)}")

        while True:
            try:
                userinput = input('--> ')
                if (userinput.strip() == ''): continue
                params = userinput.strip().split()
                command = params[0]

                if (command == 'e'):
                    if self.commRunning:
                        self.stopCommEvent.set()
                        self.commThread.join()
                    cmd.error("Terminated :)")  # 'error' is just for visual standing out
                    exit(0)

                elif command in ('h', 'help'):
                    if len(params) > 1:
                        command = params[1]
                        if (command not in commandsHelp):
                            raise CommandError(f"No such command '{command}'")
                        cmd.info(" — ".join(commandsHelp[command]))
                    else:
                        commandsColumnWidth = max(len(desc[0]) for desc in commandsHelp.values())
                        for desc in commandsHelp.values():
                            cmd.info(f"{desc[0].rjust(commandsColumnWidth)} — {desc[1]}")

                elif command in ('sh', 'show'):
                    if len(params) < 2:
                        raise CommandError("Specify what to show")
                    elem = params[1]
                    if elem in ('com', 'int', 'comm'):
                        cmd.info(f"Device interface: {self.devInt}")
                        cmd.info(f"Control soft interface: {self.appInt}")
                    elif elem in ('d', 'dev', 'device', 'p', 'protocol'):
                        cmd.info(self.device)
                    elif elem in ('conf', 'config'):
                        for par in self.CONFIG.__dict__:
                            if par == par.strip('__'):
                                cmd.info(f"{par} = {getattr(self.CONFIG, par)}")
                    elif elem in ('this', 'self', 'app', 'state'):
                        cmd.info(NotImplemented)
                    else: raise CommandError(f"No such parameter '{elem}'")

                elif not self.device and command != 'p':
                    raise ApplicationError("Target device is not defined. Define with 'p <deviceName>'")

                elif command == 's':
                    if self.commRunning: self.stop()
                    else: self.start()

                elif command in ('n', 'native'):
                    self.interactWithNativeSoft = not self.interactWithNativeSoft
                    cmd.info(f"{'Enabled' if self.interactWithNativeSoft else 'Disabled'} "
                             f"interaction with {self.device.name} native control soft")

                elif command == 'com':
                    if len(params) < 3:
                        raise CommandError("Target com port and new port number should be specified")
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
                        raise CommandError("New device name should be specified")
                    newDeviceName = params[1].lower()
                    if newDeviceName not in self.DEVICES:
                        raise CommandError(f"No such device: '{newDeviceName}'")
                    self.setProtocol(newDeviceName)

                else: raise CommandError(f"Wrong command '{command}'")

            except ApplicationError as e: cmd.showError(e)
            except Exception as e: cmd.showStackTrace(e)


if __name__ == '__main__':
    Logger.LOGGERS["Device"].setLevel("INFO")
    App()
