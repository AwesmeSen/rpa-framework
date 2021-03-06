import importlib
import logging
import os
import platform
import re
import subprocess

# import selenium
import tempfile
import time
from pathlib import Path

from SeleniumLibrary import SeleniumLibrary
from SeleniumLibrary.base import keyword
from selenium.common.exceptions import WebDriverException

from webdrivermanager import AVAILABLE_DRIVERS


class BrowserNotFoundError(Exception):
    """Raised when browser can't be initialized."""


class Browser(SeleniumLibrary):
    """RPA Framework library for Browser operations.

    Extends functionality of SeleniumLibrary.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    AUTOMATIC_BROWSER_SELECTION = "AUTO"

    AVAILABLE_OPTIONS = {
        "chrome": "ChromeOptions",
        # "firefox": "FirefoxOptions",
        # "safari": "WebKitGTKOptions",
        # "ie": "IeOptions",
    }

    CHROMEDRIVER_VERSIONS = {
        "81": "81.0.4044.69",
        "80": "80.0.3987.106",
        "79": "79.0.3945.36",
    }
    CHROME_VERSION_PATTERN = r"(\d+)(\.\d+\.\d+.\d+)"

    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(__name__)
        SeleniumLibrary.__init__(self, *args, **kwargs)
        self.drivers = []
        self.logger.debug(f"seleniumlibrary drivers {self.drivers}")

    def get_preferable_browser_order(self):
        """Returns list of RPA Framework preferred browsers by OS.

        :return: browser list
        """
        preferable_browser_order = ["Chrome"]
        if platform.system() == "Windows":
            preferable_browser_order.extend(["Firefox", "Edge", "IE", "Opera"])
        elif platform.system() == "Linux":
            preferable_browser_order.extend(["Firefox", "Opera"])
        elif platform.system() == "Darwin":
            preferable_browser_order.extend(["Safari", "Firefox", "Opera"])
        else:
            preferable_browser_order.extend(["Firefox"])
        return preferable_browser_order

    @keyword
    def open_available_browser(
        self,
        url,
        use_profile=False,
        headless=False,
        maximized=False,
        browser_selection=AUTOMATIC_BROWSER_SELECTION,
    ):
        """Open available browser

        Keywords opens the first available browser it can find from the
        system in preferred order or given browser (`browser_selection`)

        Steps:

        1. Get order of browsers
        2. Loop list of preferred of browsers

            a. Set webdriver options for browser
            b. Create webdriver using existing installaiton
            c. (If step b. failed) Download and install webdriver, try again
            d. (If step c. failed) Try starting webdriver in headless mode

        3. Open url

        If unable to open browser raises `BrowserNotFoundError`.

        Details on `Safari webdriver setup`_.

        :param url: address to open
        :param use_profile: set browser profile, defaults to False
        :param headless: run in headless mode, defaults to False
        :param maximized: run window maximized, defaults to False
        :param browser_selection: browser name, defaults to AUTOMATIC_BROWSER_SELECTION
        :return: index of the webdriver session

        .. _Safari webdriver setup:
            https://developer.apple.com/documentation/webkit/testing_with_webdriver_in_safari
        """
        index = -1
        preferable_browser_order = self.get_browser_order(browser_selection)
        selected_browser = None

        self.logger.info(
            f"Open Available Browser preferable browser selection order is: "
            f"{', '.join(preferable_browser_order)}"
        )
        for browser in preferable_browser_order:
            options = self.set_driver_options(
                browser, use_profile=use_profile, headless=headless, maximized=maximized
            )

            # First try: Without any actions
            self.logger.info("Initializing webdriver with default options (method 1)")
            index = self.create_rpa_webdriver(browser, options)
            if index is not False:
                selected_browser = (browser, 1)
                break

            self.logger.info("Could not init webdriver using method 1. ")

            # Second try: Install driver (if there is a manager for driver)
            self.logger.info("Initializing webdriver with downloaded driver (method 2)")
            index = self.create_rpa_webdriver(browser, options, download=True)
            if index is not False:
                selected_browser = (browser, 2)
                break

            self.logger.info("Could not init webdriver using method 2.")

            # Third try: Headless
            if headless is False:
                options = self.set_driver_options(
                    browser,
                    use_profile=use_profile,
                    headless=True,
                    maximized=maximized,
                )
                self.logger.info("Initializing webdriver in headless mode (method 3)")
                index = self.create_rpa_webdriver(browser, options, download=True)
                if index is not False:
                    selected_browser = (browser, 3)
                    break

        if selected_browser:
            self.logger.info(
                f"Selected browser (method: {selected_browser[1]}) "
                f"is: {selected_browser[0]}, index: {index}"
            )
            self.go_to(url)
            return index
        else:
            self.logger.error(
                f"Unable to initialize webdriver "
                f"({', '.join(preferable_browser_order)})"
            )
            raise BrowserNotFoundError

    def create_rpa_webdriver(self, browser, options, download=False):
        """Create webdriver instance for given browser.

        Driver will be downloaded if it does not exist when `download` is True.

        :param browser: name of the browser
        :param options: options for webdriver
        :param download: True if driver should be download, defaults to False
        :return: index of the webdriver session, False if webdriver was not initialized
        """
        executable = False
        self.logger.debug(f"Driver options for create_rpa_webdriver: {options}")
        executable = self.webdriver_init(browser, download)
        try:
            if executable:
                index = self.create_webdriver(
                    browser, **options, executable_path=executable
                )
            else:
                index = self.create_webdriver(browser, **options)
            return index
        except WebDriverException as err:
            self.logger.info(f"Could not open driver: {err}")
            return False
        return False

    def get_browser_order(self, browser_selection):
        """Get list of browser that will be used for open browser
        keywords. Will be one or many.

        :param browser_selection: "AUTO" will be OS specfic list,
            or one named browser, eg. "Chrome"
        :return: list of browsers
        """
        if browser_selection == self.AUTOMATIC_BROWSER_SELECTION:
            preferable_browser_order = self.get_preferable_browser_order()
        else:
            preferable_browser_order = (
                browser_selection
                if isinstance(browser_selection, list)
                else [browser_selection]
            )
        return preferable_browser_order

    def detect_chrome_version(self):
        """Detect Chrome browser version (if possible) on different
        platforms using different commands for each platform.

        Returns corresponding chromedriver version if possible.

        Supported Chrome major versions are 81, 80 and 79.

        :return: chromedriver version number or False
        """
        # pylint: disable=line-too-long
        OS_CMDS = {
            "Windows": [
                r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',  # noqa
                r'reg query "HKEY_CURRENT_USER\Software\Chromium\BLBeacon" /v version',  # noqa
            ],
            "Linux": [
                "chromium --version",
                "chromium-browser --version",
                "google-chrome --version",
            ],
            "Darwin": [
                r"/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version",  # noqa
                r"/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version",  # noqa
                r"/Applications/Chromium.app/Contents/MacOS/Chromium --version",
            ],
        }
        CMDS = OS_CMDS[platform.system()]
        for cmd in CMDS:
            output = self._run_command_return_output(cmd)
            if output:
                version = re.search(self.CHROME_VERSION_PATTERN, output)
                if version:
                    major = version.group(1)
                    detailed = version.group(0)
                    self.logger.info(f"Detected Chrome major version is: {detailed}")
                    return (
                        self.CHROMEDRIVER_VERSIONS[major]
                        if (major in self.CHROMEDRIVER_VERSIONS.keys())
                        else False
                    )
        return False

    def _run_command_return_output(self, command):
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
            )
            output, _ = process.communicate()
            return str(output).strip()
        except FileNotFoundError:
            self.logger.debug(f'Command "{command}" not found')
            return False

    def get_installed_chromedriver_version(self, driver_executable_path):
        """Returns full version number for stable chromedriver.

        Stable version is defined internally based on the major version
        of the chromedriver.

        :param driver_executable_path: path to chromedriver
        :return: full version number for stable chromedriver or False
        """
        output = self._run_command_return_output(driver_executable_path)
        if output:
            version = re.search(self.CHROME_VERSION_PATTERN, output)
            if version:
                major = version.group(1)
                detailed = version.group(0)
                self.logger.info(f"Detected chromedriver major version is: {detailed}")
                return (
                    self.CHROMEDRIVER_VERSIONS[major]
                    if (major in self.CHROMEDRIVER_VERSIONS.keys())
                    else False
                )
        return False

    def download_driver(self, dm_class, download_dir, version=None):
        """ Download driver to given directory. By default downloads
        latest version for given webdriver type, but this can be
        overridden by giving ``version`` parameter.

        :param dm_class: driver manager class
        :param download_dir: directory to download driver into
        :param version: None by default (gets latest version)
        """
        self.logger.info(f"Downloading driver into: {str(download_dir)}")
        dm = dm_class(download_root=download_dir, link_path=download_dir)
        try:
            if version:
                dm.download_and_install(version)
            else:
                dm.download_and_install()
            self.logger.debug(
                f"{dm.get_driver_filename()} downloaded into {str(download_dir)}"
            )
        except RuntimeError:
            pass

    def _set_driver_paths(self, dm_class, download):
        driver_executable_path = None

        dm = dm_class()
        driver_executable = dm.get_driver_filename()
        default_executable_path = Path(dm.link_path) / driver_executable

        tempdir = os.getenv("TEMPDIR") or tempfile.gettempdir()
        driver_tempdir = Path(tempdir) / "drivers"
        temp_executable_path = Path(driver_tempdir) / driver_executable

        if temp_executable_path.exists() or download:
            driver_executable_path = temp_executable_path
        else:
            driver_executable_path = default_executable_path
        return driver_executable_path, driver_tempdir

    def _check_chrome_and_driver_versions(self, driver_ex_path, browser_version):
        download_driver = False
        chromedriver_version = self.get_installed_chromedriver_version(
            str(driver_ex_path / " --version")
        )
        if chromedriver_version is False:
            self.logger.info("Could not detect chromedriver version.")
            download_driver = True
        elif chromedriver_version != browser_version:
            self.logger.info("Chrome and chromedriver versions are different.")
            download_driver = True
        return download_driver

    def webdriver_init(self, browser, download=False):
        """Webdriver initialization with default driver
        paths or with downloaded drivers.

        :param browser: use drivers for this browser
        :param download: if True drivers are downloaded, not if False
        :return: path to driver or `None`
        """
        self.logger.debug(
            f"Webdriver initialization for browser: '{browser}'. "
            f"Download set to: {download}"
        )
        browser_version = self.detect_chrome_version()
        dm_class = (
            AVAILABLE_DRIVERS[browser.lower()]
            if browser.lower() in AVAILABLE_DRIVERS.keys()
            else None
        )
        if dm_class:
            self.logger.debug(f"Driver manager class: {dm_class}")
            driver_ex_path, driver_tempdir = self._set_driver_paths(dm_class, download)
            if download:
                if not driver_ex_path.exists():
                    self.download_driver(dm_class, driver_tempdir, browser_version)
                else:
                    if browser.lower() == "chrome":
                        force_download = self._check_chrome_and_driver_versions(
                            driver_ex_path, browser_version
                        )
                        if force_download:
                            self.download_driver(
                                dm_class, driver_tempdir, browser_version
                            )
                    else:
                        self.logger.info(
                            f"Driver download skipped, because it already existed at "
                            f"{str(driver_ex_path)}"
                        )
            else:
                self.logger.info(f"Using already existing driver at: {driver_ex_path}")

            return r"%s" % str(driver_ex_path)
        else:
            return None

    def set_driver_options(
        self, browser, use_profile=False, headless=False, maximized=False,
    ):
        """Set options for given browser

        Supported at the moment:
            - ChromeOptions
            - FirefoxOptions
            - IeOptions

        :param browser
        :param use_profile: if browser user profile is used, defaults to False
        :param headless: if headless mode should be set, defaults to False
        :param maximized: if browser should be run maximized, defaults to False
        :return: driver options or empty dictionary
        """
        browser_options = None
        driver_options = {}
        browser_option_class = (
            self.AVAILABLE_OPTIONS[browser.lower()]
            if browser.lower() in self.AVAILABLE_OPTIONS.keys()
            else None
        )
        if browser_option_class is None:
            return driver_options

        if browser.lower() in self.AVAILABLE_OPTIONS.keys():
            module = importlib.import_module(f"selenium.webdriver")
            class_ = getattr(module, browser_option_class)
            browser_options = class_()
            self.logger.debug(type(browser_options))
            # self.set_default_options(browser_options)

        if browser_options and browser.lower() == "chrome":
            self.set_default_options(browser_options)
            prefs = {"safebrowsing.enabled": "true"}
            browser_options.add_experimental_option(
                "excludeSwitches", ["enable-logging"]
            )
            browser_options.add_experimental_option("prefs", prefs)
            if self.logger.isEnabledFor(logging.DEBUG):
                driver_options["service_log_path"] = "chromedriver.log"
                driver_options["service_args"] = ["--verbose"]

        if headless:
            self.set_headless_options(browser, browser_options)

        if browser_options and maximized:
            self.logger.info("Setting maximized mode")
            browser_options.add_argument("--start-maximized")

        if browser_options and use_profile:
            self.set_user_profile(browser_options)

        if browser_options and browser.lower() != "chrome":
            driver_options["options"] = browser_options
        else:
            driver_options["chrome_options"] = browser_options

        return driver_options

    @keyword
    def open_chrome_browser(
        self, url, use_profile=False, headless=False, maximized=False
    ):
        """Open Chrome browser.

        :param url: address to open
        :param use_profile: [description], defaults to True
        :param headless: [description], defaults to False
        """
        # webdrivermanager
        # https://stackoverflow.com/questions/41084124/chrome-options-in-robot-framework
        self.open_available_browser(
            url,
            use_profile=use_profile,
            headless=headless,
            maximized=maximized,
            browser_selection="Chrome",
        )

    def set_default_options(self, options):
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--remote-debugging-port=12922")
        options.add_argument("--no-sandbox")

    def set_headless_options(self, browser, options):
        """Set headless mode if possible for the browser

        :param browser: string name of the browser
        :param options: browser options class instance
        """
        if browser.lower() == "safari":
            self.logger.info(
                "Safari does not support headless mode. "
                "https://github.com/SeleniumHQ/selenium/issues/5985"
            )
            return
        if options:
            self.logger.info("Setting headless mode")
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-dev-shm-usage")

    def set_user_profile(self, options):
        user_profile_dir = os.getenv("RPA_CHROME_USER_PROFILE_DIR", None)
        if user_profile_dir is None:
            self.logger.warning(
                'environment variable "RPA_CHROME_USER_PROFILE_DIR" '
                "has not been set, cannot set user profile"
            )
            return
        options.add_argument(f"--user-data-dir='{user_profile_dir}'")
        options.add_argument("--enable-local-sync-backend")
        options.add_argument(f"--local-sync-backend-dir='{user_profile_dir}'")

    @keyword
    def open_headless_chrome_browser(self, url):
        """Open Chrome browser in headless mode

        :param url: address to open
        """
        self.open_chrome_browser(url, headless=True)

    @keyword
    def screenshot(self, page=True, locator=None, filename_prefix="screenshot"):
        """Capture page and/or element screenshot

        :param page: capture page screenshot, defaults to True
        :param locator: if defined take element screenshot, defaults to None
        :param filename_prefix: prefix for screenshot files, default to 'screenshot'
        """
        if page:
            filename = os.path.join(
                os.curdir, f"{filename_prefix}-%s-page.png" % int(time.time())
            )
            capture_location = self.capture_page_screenshot(filename)
            self.logger.info(
                "Page screenshot saved to %s", Path(capture_location).resolve()
            )
        if locator:
            filename = os.path.join(
                os.curdir, f"{filename_prefix}-%s-element.png" % int(time.time())
            )
            capture_location = self.capture_element_screenshot(
                locator, filename=filename
            )
            self.logger.info(
                "Element screenshot saved to %s", Path(capture_location).resolve()
            )

    @keyword
    def input_text_when_element_is_visible(self, locator, text):
        """Input text into locator after it has become visible

        :param locator: selector
        :param text: insert text to locator
        """
        self.wait_until_element_is_visible(locator)
        self.input_text(locator, text)

    @keyword
    def wait_and_click_button(self, locator):
        """Click button once it becomes visible

        :param locator: [description]
        """
        self.wait_until_element_is_visible(locator)
        self.click_button(locator)

    @property
    def location(self):
        """Return browser location

        :return: url of the page browser is in
        """
        return self.get_location()
