from __future__ import annotations

from itertools import compress
from os import linesep
from os.path import join as joinpath, dirname, abspath, isdir
from typing import Dict, Type, Set

from logger import Logger
from ruamel.yaml import YAML, YAMLError
from utils import formatDict

log = Logger("Config")


CONFIG_CLASSES: Set[Type[ConfigLoader]] = set()
CONFIGS_DICT: Dict[str, dict] = {}


class ConfigLoader:
    """ When subclassed, stores all UPPERCASE (of which isupper() returns True)
        class attrs as dict of categories with config parameters
        and saves/loads them to/from .yaml file """

    # CONSIDER: override setattr() to set ConfigLoader attrs (like .filePath and .loader), not child class

    configFileName: str = 'config.yaml'
    filePath: str = joinpath(dirname(abspath(__file__)), configFileName)
    loader = YAML(typ='safe')
    loader.default_flow_style = False
    loaded = False

    section: str = None  # initialized in successors

    @classmethod
    def load(cls, section: str, path: str = None):
        """ Update config object with retrieved config file params """

        if cls is ConfigLoader:
            raise NotImplementedError("ConfigLoader is intended to be used by subclassing")

        cls.section = section

        if cls._validateConfigFilePath_(path):
            cls.filePath = joinpath(path, cls.configFileName)

        log.debug(f"Config file path: {cls.filePath}")

        if not CONFIGS_DICT:  # => call ConfigLoader for the first time => load config from .yaml file
            if not cls._loadFromFile_():  # => non existent or empty file => no profit, use defaults
                return  # ◄ use class attrs when querying config params

        try:
            configFileDict = CONFIGS_DICT[cls.section].copy()
        except KeyError:
            log.warning(f"Cannot find section {cls.section} in config file. Creating new one with defaults.")
            cls._addCurrentSection_()
            return  # ◄ use class attrs when querying config params

        CONFIG_CLASSES.add(cls)

        for parName in cls.params():
            currPar = getattr(cls, parName)
            try: newPar = configFileDict.pop(parName)
            except KeyError:
                log.error(f"Parameter {parName}: not found in config file {cls.configFileName}")
            else:
                if currPar is not None and newPar is not None:
                    # cast to current type
                    try: newPar = type(currPar)(newPar)
                    except (ValueError, TypeError) as e:
                        log.error(f"Parameter {parName}: cannot convert '{newPar}' "
                                  f"to type '{type(currPar).__name__}': {e}")
                        continue
                setattr(cls, parName, newPar)
        if len(configFileDict) != 0:
            log.warning(f"Unexpected parameters found in configuration file: {', '.join(configFileDict)}")
            currSectionDict = CONFIGS_DICT[cls.section]
            for par in configFileDict: del currSectionDict[par]

        cls.loaded = True
        log.info(f"Config '{cls.section}' loaded: "
                  f"{formatDict({name: getattr(cls, name) for name in cls.params()})}")

    @classmethod
    def update(cls):  # CONSIDER: (True, 2, 3.0) == (1,2,3) as well as [1,2] != (1,2) => need to compare types as well
        assert CONFIGS_DICT
        storedConfig = tuple(CONFIGS_DICT[cls.section].values())
        CONFIGS_DICT[cls.section].update({name: getattr(cls, name) for name in cls.params()})
        # ▼   stored config != current config
        return storedConfig != tuple(CONFIGS_DICT[cls.section].values())

    @classmethod
    def save(cls, forceSave=False):
        """ Save all config sections to config file if any have changed or if forced
            NOTE: Call this method before app exit """

        # ▼ return here if no config file creation is required in case no valid one was found
        if not CONFIG_CLASSES: log.warning("No informative config file found")
        # if any(config.section in CONFIGS_DICT for config in CONFIG_CLASSES): forceSave = True
        if not cls._fileUpdateRequired_() and not forceSave:
            configChanged = tuple(cls.update() for cls in CONFIG_CLASSES)
            if not any(configChanged):
                log.info('Config does not change, no need to save')
                return
            else:
                # ▼ the iteration order on the SET is consistent within single execution run, so results will be aligned
                log.debug("Config changed for: "
                          f"{', '.join(configCls.section for configCls in compress(CONFIG_CLASSES, configChanged))}")
        try:
            with open(cls.filePath, 'w') as configFile:
                cls.loader.dump(CONFIGS_DICT, configFile)
                log.info(f"Config saved, {len(CONFIGS_DICT)} sections: {' ,'.join(CONFIGS_DICT)}")
        except (PermissionError, YAMLError) as e:
            log.error(f"Failed to save configuration file:{linesep}{e}")

    @classmethod
    def _addCurrentSection_(cls):
        CONFIGS_DICT[cls.section] = {parName: getattr(cls, parName) for parName in cls.params()}
        log.debug(f"New section added: {cls.section} {formatDict(CONFIGS_DICT[cls.section])}")

    @classmethod
    def _loadFromFile_(cls) -> bool:
        """ Load dict of config sections from .yaml file to CONFIGS_DICT module variable,
            return boolean value = failed/succeeded """

        # CONSIDER: restore previous config (create .bak file) option
        #  and add functionality to revert() config from that backup


        try:
            with open(cls.filePath) as configFile:
                # ▼ expect dict of config dicts in config file
                configDict = cls.loader.load(configFile)
                if configDict is None:
                    log.warning(f"Config file is empty")
                    cls._addCurrentSection_()
                elif not isinstance(configDict, dict):
                    raise TypeError(f"Config loader {cls.loader.__name__} "
                                    f"returned invalid result type: {type(configDict)}")
                else:
                    log.debug(f"CONFIGS DICT: {formatDict(configDict)}")
                    CONFIGS_DICT.update(configDict)
                    return True  # succeeded loading from file
        except YAMLError as e:
            log.error(f"Failed to parse configuration file:{linesep}{e}")
        except FileNotFoundError:
            log.warning(f"Config file {cls.configFileName} not found. Defaults will be used")
            cls._addCurrentSection_()

    @classmethod
    def ignoreChanges(cls, ignore=True):
        return NotImplementedError  #FIXME: redesign not to touch CONFIG_CLASSES, mb create dedicated flags tuple
        if ignore is True:
            CONFIG_CLASSES.remove(cls)
        elif ignore is False:
            CONFIG_CLASSES.add(cls)
        else: raise ValueError(f"Boolean value expected, not {ignore}")

    @classmethod
    def params(cls):
        yield from (attrName for attrName in vars(cls) if attrName.isupper())

    @classmethod
    def _fileUpdateRequired_(cls): return not all(configClass.loaded for configClass in CONFIG_CLASSES)

    @staticmethod
    def _validateConfigFilePath_(path: str):
        if path is None:
            return None  # use default config file path (project path)
        elif not isdir(path):
            log.error(f"Invalid directory: {path}. Defaults will be used")
            return False
        return True


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

    TestConfig.save()

    print(f"TestConfig.P2: {TestConfig.P1}")
    print(f"TestConfig.P3: {TestConfig.P3}")
