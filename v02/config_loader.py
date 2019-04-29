from __future__ import annotations

from os import linesep
from os.path import join as joinpath, dirname, abspath, isdir
from typing import Optional, Dict, List, Type, Set

from logger import Logger
from ruamel.yaml import YAML, YAMLError
from utils import formatDict

log = Logger("Config")


CONFIG_CLASSES: Set[Type[ConfigLoader]] = set()
CONFIGS_DICT: Dict[str, dict] = None


class ConfigLoader:
    """ When subclassed, stores all UPPERCASE (of which isupper() returns True)
        class attrs as dict of categories with config parameters
        and saves/loads them to/from .yaml file """

    configFileName: str = 'config.yaml'
    filePath: str = joinpath(dirname(abspath(__file__)), configFileName)
    loader = YAML(typ='safe')
    loader.default_flow_style = False

    _section_: str = None  # initialized in successors

    @classmethod
    def load(cls, section: str, path: str = None):
        """ Update config object with retrieved config file params """

        if cls is ConfigLoader:
            raise NotImplementedError("ConfigLoader is intended to be used by subclassing")
        if path is not None:
            if not isdir(path):
                raise ValueError(f"Invalid directory: {path}")
            cls.filePath = joinpath(path, cls.configFileName)

        CONFIG_CLASSES.add(cls)

        log.debug(f"Config file path: {cls.filePath}")
        cls._section_ = section

        global CONFIGS_DICT  # :/
        if CONFIGS_DICT is None:  # call ConfigLoader for the first time ——► load config from .yaml file
            CONFIGS_DICT = dict(cls._loadFromFile_())
            log.debug(f"CONFIGS DICT: {formatDict(CONFIGS_DICT) if CONFIGS_DICT else '<None>'}")
            if CONFIGS_DICT is None:  # configDict is still None ——► configDict construction from .yaml file failed
                return  # ◄ use class attrs when querying config params

        try:
            configFileDict = CONFIGS_DICT[cls._section_]
        except KeyError:
            log.warning(f"Cannot find section {cls._section_} in config file. Creating new one with defaults.")
            CONFIGS_DICT[cls._section_] = {parName: getattr(cls, parName) for parName in cls.params()}
            log.debug(f"New section added: {cls._section_} {formatDict(CONFIGS_DICT[cls._section_])}")
            return  # ◄ use class attrs when querying config params

        missingParams, invalidTypeParams = [], []
        for parName in cls.params():
            currPar = getattr(cls, parName)
            try: newPar = configFileDict.pop(parName)
            except KeyError: missingParams.append(parName)
            else:
                try: newPar = type(currPar)(newPar) if currPar is not None else newPar
                except (ValueError, TypeError) as e:
                    log.error(f"Parameter {parName}: cannot convert {newPar} to type '{type(currPar).__name__}': {e}")
                else: setattr(cls, parName, newPar)
        if missingParams:
            log.warning(f"Following parameters was not found in config file: {', '.join(missingParams)}")
        if len(configFileDict) != 0:
            log.warning(f"Unexpected parameters found in configuration file: {', '.join(configFileDict.keys())}")
        log.debug(f"Config '{cls._section_}' loaded: {formatDict({name: getattr(cls, name) for name in cls.params()})}")

    @classmethod
    def _loadFromFile_(cls) -> Optional[dict]:
        """ Load dict of config sections from .yaml file """

        # CONSIDER: restore previous config (create .bak file) option
        #  and add functionality to revert() config from that backup

        try:
            with open(cls.filePath) as configFile:
                # ▼ expect dict of config dicts in config file
                configDict = cls.loader.load(configFile)
                if configDict is None:
                    log.warning("Loaded empty config from file")
                elif not isinstance(configDict, dict):
                    raise TypeError(f"Config loader {cls.loader.__name__} "
                                    f"returned invalid result type: {type(configDict)}")
                return configDict
        except YAMLError as e:
            log.error(f"Failed to parse configuration file:{linesep}{e}")
        except FileNotFoundError:
            log.warning(f"Config file {cls.configFileName} not found. Generating new one with defaults.")
            cls.saveToFile()

    @classmethod
    def update(cls):
        storedConfig = CONFIGS_DICT[cls._section_].values()
        CONFIGS_DICT[cls._section_].update({name: getattr(cls, name) for name in cls.params()})
        # ▼   stored config != current config
        return storedConfig != CONFIGS_DICT[cls._section_].values()

    @staticmethod
    def saveToFile():
        # NOTE: Call this method before app exit
        for cls in CONFIG_CLASSES:
            configChanged = cls.update()
            log.debug(f"Config changed: {configChanged}")
            if configChanged:
                try:
                    with open(cls.filePath, 'w') as configFile:
                        return cls.loader.dump(CONFIGS_DICT, configFile)
                except (PermissionError, YAMLError) as e:
                    log.error(f"Failed to save configuration file:{linesep}{e}")

    @classmethod
    def ignoreChanges(cls, ignore=True):
        if ignore is True:
            CONFIG_CLASSES.remove(cls)
        elif ignore is False:
            CONFIG_CLASSES.add(cls)
        else: raise ValueError(f"Boolean value expected, not {ignore}")

    @classmethod
    def params(cls):
        yield from (attrName for attrName in vars(cls) if attrName.isupper())


if __name__ == '__main__':
    class TestConfig(ConfigLoader):
        P1 = 34
        P2 = 'bla bla'
        P3 = None
        P4 = [1, 2, 3, 4, 5]
        e = 'service'

    class TestConfig2(ConfigLoader):
        P1 = 'azaza'
        P2 = ('a', 'b', 'c', 'd', 'e')
        P3 = None
        s = 'service2'

    ConfigLoader.configFileName = 'testconfig.yaml'
    wd = r"D:\GLEB\Python\ProtocolProxy\v02"

    print(f"TestConfig dir: {formatDict(vars(TestConfig))}")
    print(f"TestConfig2 dir: {formatDict(vars(TestConfig2))}")

    TestConfig.load('APP', wd)
    TestConfig2.load('TEST', wd)

    print("TestConfig (loaded) params: \n" + linesep.join(
            f"    {name} = {getattr(TestConfig, name)}" for name in TestConfig.params()))
    print("TestConfig2 (loaded) params: \n" + linesep.join(
            f"    {name} = {getattr(TestConfig2, name)}" for name in TestConfig2.params()))

    input("Enter to save config...")

    print(f"TestConfig.P2: {TestConfig.P1}")
    print(f"TestConfig.P3: {TestConfig.P3}")

    TestConfig.P1 = 'newP1'
    TestConfig.P3 = 'newP2'

    TestConfig.saveToFile()

    print(f"TestConfig.P2: {TestConfig.P1}")
    print(f"TestConfig.P3: {TestConfig.P3}")
