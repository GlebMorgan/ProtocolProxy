import importlib
from threading import Thread, Event
from contextlib import contextmanager
from os import listdir, linesep, makedirs
from os.path import abspath, dirname, isfile, join as joinpath, isdir, expandvars as envar, basename
import sys
from typing import Union, Dict, Type, Callable

from Utils import Logger, bytewise, castStr, ConfigLoader, formatDict, capital, Formatters

from device import Device, DataInvalidError
from notifier import Notifier
from Transceiver import SerialTransceiver, PelengTransceiver
from Transceiver.errors import VerboseError
from Transceiver.errors import *

# NCS - Native Control Software - external native application that is used
#       to control the device through ProtocolProxy app


log = Logger("App")
log.setLevel('DEBUG')

tlog = Logger("Transactions")
tlog.setLevel('DEBUG')


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
        self.__protocols_path__ = self.__class__.path if path is None else path
        if not isdir(self.__protocols_path__):
            makedirs(self.__protocols_path__)
        for filename in listdir(self.__protocols_path__):
            if (filename.endswith('.py') and isfile(joinpath(self.__protocols_path__, filename))):
                self.setdefault(filename[:-3].lower())
        sys.path.append(self.__protocols_path__)

    def __getitem__(self, item:str) -> Type[Device]:
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
    APP_COM_PORT: str = 'COM11'     # virtual port for App
    DEV_COM_PORT: str = 'COM1'      # real port for Device
    DEVICE_TIMEOUT: float = 0.5  # sec
    SMALL_TIMEOUT_DELAY: float = 0.5  # sec
    BIG_TIMEOUT_DELAY: int = 5  # sec
    NO_REPLY_HOPELESS: int = 50  # timeouts
    NATIVE_SOFT_COMM: bool = True


class App(Notifier):
    """
    API methods:
      • init()
      • startCmdThread()
      • setProtocol()
      • start()
      • stop()
    
    API objects:
      • device
      • CONFIG
    """

    protocols: Dict[str, Type[Device]] = None

    def __init__(self, INFO: dict):
        super().__init__()
        CONFIG.load()

        self.VERSION = INFO['version']
        self.PROJECT_NAME = INFO['projectname']
        self.PROJECT_FOLDER = INFO['projectdir']
        self.PROTOCOLS_FOLDER = ProtocolLoader.path

        self.protocols: ProtocolLoader = ProtocolLoader()

        self.cmdThread: Thread = None
        self.commThread: Thread = None
        self.ncsThread: Thread = None

        self.stopEvent: Event = None
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
                self.stopEvent.set()
            self.commThread.join()

        if self.ncsThread:
            self.stopEvent.set()
            self.ncsThread.join()

        if self.cmdThread:
            self.cmdThread.join()

        CONFIG.save()
        log.info("TERMINATED :)")

    def init(self):
        log.info(f"Project directory:   {self.PROJECT_FOLDER}")
        log.info(f"Protocols directory: {self.PROTOCOLS_FOLDER}")
        for name, level in self.loggerLevels.items(): Logger.all[name].setLevel(level)
        self.addEvents(
            'app initialized',   # All required startup initialization finished, API methods could be used
            'protocol changed',  # App reconfigured for new protocol
            'quit',              # Occurs before context-manager cleanup is performed
            'comm started',      # Communication loop is ready to start transactions
            'comm dropped',      # Failed to configure and open ports
            'comm failed',       # Fatal failure in communication loop
            'comm stopped',      # Communication loop is stopped and communication thread is about to exit
            'comm ok',           # Transaction controlSoft ⇆ app ⇆ device performed successfully
            'comm timeout',      # Write or read timeout in communication loop
            'comm error'         # Error in packet transmission process (bad data, connection lost, etc.)
        )

        self.notify('app initialized')

    def reloadProtocols(self):
        self.protocols = ProtocolLoader()

    def startCmdThread(self):
        self.cmdThread = Thread(name="CMD thread", target=self.runCmd)
        self.cmdThread.start()

    @contextmanager
    def restartNeeded(self):
        if not self.commRunning:
            yield
        else:
            self.stopComm()
            yield
            self.startComm()

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
        self.appInt.port = CONFIG.APP_COM_PORT
        self.devInt = self.getInterface(self.device.COMMUNICATION_INTERFACE)
        self.devInt.port = CONFIG.DEV_COM_PORT

    def setProtocol(self, deviceName: str):
        self.device = self.protocols[deviceName]()
        if not self.appInt and not self.devInt: self.initInterfaces()
        with self.device.lock, self.restartNeeded():
            self.device.configureInterface(self.appInt, self.devInt)
        self.notify('protocol changed', deviceName)

    def start(self, name: str, target: Callable, subject: str, openApp: bool, openDev: bool):
        """ Open requested ports and run subject (communication,
                NCS monitoring, etc.) loop in a separate thread
            Returns:
                True  ––► subject loop launched,
                False ––► subject loop is not running,
                None  –-► already running
        """
        thread = getattr(self, name)
        if thread is not None:
            log.warning(f"{subject.capitalize()} is already enabled — ignoring command")
            return None
        if not self.devInt:
            raise ApplicationError("Target device is not set")

        log.info(f"Launching {subject}...")
        try:
            if openApp is True: self.appInt.open()
            if openDev is True: self.devInt.open()
        except SerialError as e:
            if openApp is True:
                self.appInt.close()
            if openDev is True:
                self.devInt.close()
                self.notify('comm dropped')
            log.fatal(f"Failed to start {subject} loop: {e}")
            log.debug('', traceback=True)
            return False

        self.stopEvent = Event()
        thread = Thread(name="Communication thread",
                        target=target, args=(self.stopEvent,))
        thread.start()
        setattr(self, name, thread)
        return True

    def stop(self, name: str, subject: str):
        """ Stop subject (communication, NCS monitoring, etc.) loop
                and block until it exits
            Returns:
                False ––► subject stopped,
                None  –-► has been stopped already
        """
        thread = getattr(self, name)
        if not thread:
            log.warning(f"{subject.capitalize()} is already disabled — ignoring command")
            return None
        if thread.is_alive():
            log.info(f"Interrupting {subject} loop...")
            self.stopEvent.set()
        thread.join()
        self.stopEvent.clear()
        setattr(self, name, thread)
        return False

    def startComm(self):
        status = self.start(name='commThread', target=self.commLoop,
                            subject='communication', openApp=True, openDev=True)
        if status is True:
            log.info(f"Starting transactions between {self.device.name} via '{self.devInt.token}' "
                     f"and native control software via '{self.appInt.token}'...")
        return status

    def stopComm(self):
        status = self.stop(name='commThread', subject='communication')
        self.commThread = None
        return status

    def enableSmart(self):
        status = self.start(name='ncsThread', target=self.ncsLoop,
                            subject='smart mode', openApp=True, openDev=False)
        if status is True:
            log.info(f"Starting to monitor {self.device.name} NCS via '{self.appInt.token}'")

        return status

    def disableSmart(self):
        status = self.stop(name='ncsThread', subject='smart mode')
        self.ncsThread = None
        return status

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
            self.notify('comm timeout')
        except (DataInvalidError, SerialCommunicationError) as e:
            if isinstance(e, BadDataError):
                tlog.error(f"Received bad data from {subject} native control soft:\n{e}\n"
                           f"(wrong data source is connected to {self.appInt.token}?)")
            elif isinstance(e, BadCrcError):
                tlog.error(f"Checksum validation failed for packet from {subject} native control soft:\n{e}")
            elif isinstance(e, DataInvalidError):
                tlog.error(f"Invalid data received from {subject} native control soft:\n{e}")
            else:
                tlog.error(e)
            tlog.info("Packet discarded")
            if isinstance(e, VerboseError):
                tlog.debug(e)
            self.notify('comm error')
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
            self.notify('comm timeout')
            # TODO: redesign this ▼ to set new timer interval to 5x transaction period
            #  when scheduler will be used instead of 'for loop' for triggering transactions
            stopEvent.wait(CONFIG.SMALL_TIMEOUT_DELAY if self.devInt.nTimeouts < CONFIG.NO_REPLY_HOPELESS
                           else CONFIG.BIG_TIMEOUT_DELAY)
        except (DataInvalidError, SerialCommunicationError) as e:
            if isinstance(e, BadDataError):
                tlog.error(f"Received corrupted data from '{subject}' device:\n{e}")
            elif isinstance(e, BadCrcError):
                tlog.error(f"Checksum validation failed for packet from {subject} device:\n{e}")
            elif isinstance(e, DataInvalidError):
                tlog.error(f"Invalid data received from {subject} device:\n{e}")
            else:
                tlog.error(e)
            tlog.info("Packet discarded")
            if isinstance(e, VerboseError):
                tlog.debug(e)
            self.notify('comm error')
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

    def commLoop(self, stopEvent: Event):
        self.notify('comm started')
        try:
            self.commRunning = True
            self.nativeSoftConnEstablished = False
            log.info("Communication launched")
            while True:  # TODO: replace this loop with proper timing-based scheduler
                self.nativeData = self.deviceData = None
                if (stopEvent.is_set()):
                    log.info("Received stop communication command")
                    break

                with self.controlSoftErrorsHandler():
                    if self.interactWithNativeSoft:
                        self.nativeData = self.device.receiveNative(self.appInt)
                    else:
                        self.nativeData = self.device.IDLE_PAYLOAD
                if self.nativeData is None: continue

                self.nativeData = self.device.wrap(self.nativeData)
                try:
                    self.devInt.sendPacket(self.nativeData)
                except SerialWriteTimeoutError:
                    tlog.error(f"Failed to send data over '{self.devInt.token}' (device disconnected?)")
                    self.notify('comm error')
                    continue  # TODO: what needs to be done when unexpected error happens [2]?

                with self.deviceErrorsHandler(stopEvent):
                    self.deviceData = self.devInt.receivePacket()
                if self.deviceData is None: continue

                self.deviceData = self.device.unwrap(self.deviceData)
                try:
                    if self.interactWithNativeSoft and self.appInt.nTimeouts == 0:  # duck-tape-ish...
                        self.device.sendNative(self.appInt, self.deviceData)
                except SerialWriteTimeoutError:
                    if self.nativeSoftConnEstablished is False:
                        # ▼ Wait for native control soft to launch
                        if self.appInt.nTimeouts == 1:
                            tlog.info(f"Waiting for {self.device.name} native control soft to launch")
                    else:
                        tlog.error(f"Failed to send data over {self.appInt.token} "
                                   f"(native communication soft disconnected?)")
                        self.notify('comm error')
                        # TODO: what needs to be done when unexpected error happens [3]?
                self.notify('comm ok')

        except SerialError as e:
            tlog.fatal(f"Transaction failed: {e}")
            tlog.debug('', traceback=True)
            self.notify('comm failed')
            # TODO: what needs to be done when unexpected error happens [1]?
        except Exception as e:
            tlog.fatal(f"Unexpected error happened: {e}")
            tlog.error('', traceback=True)
            self.notify('comm failed')
        finally:
            self.appInt.close()
            self.devInt.close()
            self.appInt.nTimeouts = self.devInt.nTimeouts = 0
            self.commRunning = False
            self.notify('comm stopped')
            log.info("Communication stopped")

    def ncsLoop(self, stopEvent: Event):
        self.notify('comm started')
        try:
            log.debug('NCS loop launched')
            while True:
                if (stopEvent.is_set()):
                    log.info("Received stop communication command")
                    break
                try:
                    self.nativeData = self.device.receiveNative(self.appInt)
                except SerialReadTimeoutError:
                    log.debug("NCS timeout")
                    continue
                except (DataInvalidError, SerialCommunicationError) as e:
                    log.debug(f"Bad packet from NCS - {e}")
                    self.notify('comm error')
                    continue
                else:
                    state = self.transaction(data=self.nativeData, closePort=False)
                if state is True:
                    try:
                        self.device.sendNative(self.appInt, self.deviceData)
                    except SerialWriteTimeoutError:
                        log.error("NCS write timeout")
                        self.notify('comm error')
                if self.appInt.in_waiting == 0:
                    self.devInt.close()
                else:
                    self.appInt.reset_input_buffer()
        except SerialError as e:
            tlog.fatal(f"Transaction failed: {e}")
            tlog.debug('', traceback=True)
            self.notify('comm failed')
        except Exception as e:
            tlog.fatal(f"Unexpected error happened: {e}")
            tlog.error('', traceback=True)
            self.notify('comm failed')
        finally:
            self.appInt.close()
            self.devInt.close()
            self.notify('comm stopped')
            log.info("NCS loop stopped")

    def transaction(self, *_, data=None, closePort=True):
        with self.device.lock:
            if data is None: data = self.device.IDLE_PAYLOAD
            data = self.device.wrap(data)
            port = self.devInt.port

            if self.devInt.is_open is False:
                try:
                    self.devInt.open()
                except SerialError as e:
                    log.error(f"Transaction failed - cannot open port '{port}' - {e}")
                    log.debug('', traceback=True)
                    return False
            try:
                self.devInt.sendPacket(data)
            except SerialWriteTimeoutError:
                tlog.error(f"Device write timeout ({port})")
                self.notify('comm error')
                return False
            try:
                self.deviceData = self.device.unwrap(self.devInt.receivePacket())
            except SerialReadTimeoutError:
                log.warning("Device timeout")
                self.notify('comm timeout')
            except (DataInvalidError, SerialError) as e:
                log.error(f"Transaction failed - {e}")
                log.debug('', traceback=True)
            else:
                self.notify('comm ok')
                return True
            finally:
                if closePort: self.devInt.close()

    def ackTransaction(self, *_, limit=1000):
        try:
            for _ in range(limit):
                self.transaction(closePort=False)
                if self.deviceData is None: return None
                if all(par.inSync for par in self.device.params): break
            else:
                failedParams = (par.name for par in self.device.params if not par.inSync)
                log.error(f"Failed to get ack for {self.device.name} params {', '.join(failedParams)} " 
                          f"after {limit} attempts")
        finally:
            self.devInt.close()

    def suppressLoggers(self, mode: Union[str, bool] = None) -> Union[str, bool]:
        isAltered = not all((Logger.all[loggerName].levelname == level
                             for loggerName, level in self.loggerLevels.items()))
        if mode is None:
            # ▼ return whether loggers was suppressed (True) or they are as defined in self.loggerLevels (False)
            return isAltered
        if mode == 'kill':  # disable all loggers completely
            for loggerName in self.loggerLevels:
                Logger.all[loggerName].disabled = True
            return "————— Transactions logging output disabled —————".center(80)
        elif isAltered:  # enable all loggers back
            for loggerName in self.loggerLevels:
                Logger.all[loggerName].disabled = False

        if mode is False or mode == 'False':  # assign levels according to self.loggerLevels
            for loggerName, level in self.loggerLevels.items(): Logger.all[loggerName].setLevel(level)
            return "————— Transactions logging output restored —————".center(80)
        elif mode is True or mode == 'True':  # set transactions-related loggers to lower level
            for loggerName in self.loggerLevels: Logger.all[loggerName].setLevel('ERROR')
            Logger.all["Transactions"].setLevel('WARNING')
            return "————— Transactions logging output suppressed —————".center(80)
        elif mode in log.levels:  # set all loggers to given level
            for loggerName in self.loggerLevels: Logger.all[loggerName].setLevel(mode)
            return f"————— Transactions logging output set to '{mode}' level —————".center(80)
        else:
            raise ValueError(f"Invalid logging mode '{mode}'")

    @staticmethod
    def setTransactionOutputLevel(level: Union[str, int]):
        tlog.setLevel(level)
        Logger.all['Packets'].setLevel(level)

    def runCmd(self):
        cmd = Logger('AppCMD')
        cmd.consoleHandler.setFormatter(Formatters.simpleColored)
        cmd.setLevel('DEBUG')

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


        cmd.info(f"\n————— Protocol proxy v{self.VERSION} CMD interface —————".center(80))
        cmd.info(f"\n{showHelp()}")
        cmd.info(f"\nAvailable protocols: {', '.join(self.protocols)}")

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
                    try: self.__exit__(None, None, None)
                    except Exception: pass
                    self.notify('quit')
                    sys.exit(0)

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
                        if loggerName not in self.loggerLevels:
                            raise CommandError("Invalid logger name. List available loggers via 'show log'")
                        newLevelName = params[2].upper()
                        if newLevelName not in log.levels:
                            raise CommandError('Invalid logging level')
                        self.loggerLevels[loggerName] = newLevelName
                        Logger.all[loggerName].setLevel(newLevelName)
                    else: raise CommandError(f"Wrong parameters")

                elif command == '>':
                    try: cmd.info(exec(userinput[2:]))
                    except Exception as e: cmd.error(f"Execution error: {e}")

                elif not self.device and command != 'p':
                    raise CommandError("Target device is not defined. Define with 'p <deviceName>'")

                elif command == 's':
                    if self.commRunning:
                        if self.suppressLoggers():
                            cmd.info(self.suppressLoggers(False))
                        self.stopComm()
                    else:
                        self.startComm()

                elif command == 'r':
                    if self.commRunning:
                        if self.suppressLoggers():
                            cmd.info(self.suppressLoggers(False))
                        self.stopComm()
                        self.startComm()
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

            except CommandError as e: cmd.error(e)
            except ApplicationError as e: cmd.error(e)
            except NotImplementedError as e: cmd.error(e)
            except SerialCommunicationError as e: cmd.error(e)
            except Exception as e: cmd.error(e, traceback=True)


if __name__ == '__main__':
    from shutil import copyfile

    log.debug(f"Launched from: {abspath(__file__)}")

    Logger.all["Device"].setLevel("INFO")
    Logger.all["Config"].setLevel("DEBUG")
    ConfigLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy')
    ProtocolLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy', 'devices')

    try:
        copyfile(joinpath(dirname(abspath(__file__)), 'devices', 'sony.py'),
                 joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy\\devices', 'sony.py'))
        copyfile(joinpath(dirname(abspath(__file__)), 'devices', 'mwxc.py'),
                 joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy\\devices', 'mwxc.py'))
    except FileNotFoundError as e:
        log.error(f"Cannot copy devices from development dir to config dir:\n    {e}")

    INFO = {
        'version': '[cmd]',
        'projectname': 'ProtocolProxy',
        'projectdir': dirname(abspath(__file__).strip('.pyz')),
    }

    with App(INFO) as app:
        app.init()
        app.startCmdThread()
