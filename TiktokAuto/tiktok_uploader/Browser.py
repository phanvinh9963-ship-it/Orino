from .cookies import load_cookies_from_file, save_cookies_to_file
from fake_useragent import UserAgent, FakeUserAgentError
import undetected_chromedriver as uc
import subprocess, threading, os, platform, re


WITH_PROXIES = False

# ===================== CONFIG - SUA O DAY NEU CAN =====================
# True  = mo Chrome bang 1 PROFILE RIENG, doc lap, KHONG dinh gi den Chrome
#         that ban dung hang ngay -> khong can dong Chrome khac. Lan dau se
#         la Chrome trang (chua dang nhap gi), ban dang nhap TikTok 1 lan,
#         cac lan sau tool tu nho (day la thu muc luu persistent, khong phai
#         profile tam thoi bi xoa sau moi lan chay).
# False = uc tu tao profile tam thoi hoan toan trong moi lan chay (khong nho
#         gi giua cac lan, phai dang nhap lai tu dau moi lan).
USE_EXISTING_CHROME_PROFILE = True

# Ten thu muc con trong CHROME_USER_DATA_DIR - khong lien quan gi den Profile
# that cua Chrome ca nhan, day la thu muc rieng tool nay tu tao va quan ly.
#
# QUAN TRONG: MOI TAI KHOAN PHAI CO 1 PROFILE RIENG BIET, khong dung chung
# "Default" cho tat ca - neu dung chung, tai khoan dang nhap SAU se ke thua
# nguyen session cua tai khoan dang nhap TRUOC (Chrome van con dang nhap san
# tu lan truoc), gay ra loi "Unnecessary login: session already saved!" va 2
# tai khoan bi luu TRUNG cookie cua nhau. Ten profile lay tu bien moi truong
# TIKTOK_PROFILE_NAME (main.py tu dat truoc khi goi cli.py login/upload cho
# tung tai khoan) - neu khong co (vd chay tay khong qua app) thi fallback ve
# "Default" nhu truoc, giu tuong thich nguoc.
def _sanitize_profile_name(name: str) -> str:
    """Chuyen ten tai khoan thanh ten thu muc Windows hop le (bo ky tu cam)."""
    safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return safe or "default"


_account_profile_name = os.environ.get("TIKTOK_PROFILE_NAME", "").strip()
CHROME_PROFILE_DIRECTORY = (
    f"Account_{_sanitize_profile_name(_account_profile_name)}" if _account_profile_name else "Default"
)

# Thu muc luu profile rieng cua tool nay - dat NGAY BEN TRONG thu muc
# TiktokAuto (thu muc cha cua tiktok_uploader/) de tu chua gon, KHONG dinh gi
# den thu muc "User Data" that cua Chrome Windows ban dung hang ngay.
CHROME_USER_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chrome_profile_data"
)
# ========================================================================


def _get_chrome_major_version() -> int:
    """Detect the major version of the system-installed Chrome so
    undetected-chromedriver downloads/patches a matching ChromeDriver binary.

    Tries, in order:
      1. Windows registry (BLBeacon key Chrome writes after it has run once).
      2. `chrome.exe` / `google-chrome` binaries on PATH via --version.
      3. Common Windows install paths, reading file version via PowerShell.
    Falls back to 0 (uc will use "latest") if nothing is found.
    """
    system = platform.system()

    if system == "Windows":
        # 1) Registry BLBeacon (written by Chrome itself, very reliable).
        try:
            out = subprocess.check_output(
                ["reg", "query", r"HKCU\Software\Google\Chrome\BLBeacon", "/v", "version"],
                stderr=subprocess.DEVNULL,
            ).decode(errors="ignore")
            match = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
            if match:
                return int(match.group(1))
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # 2) Common install paths, ask PowerShell for the file's ProductVersion.
        candidate_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Google", "Chrome", "Application", "chrome.exe",
            ),
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                try:
                    out = subprocess.check_output(
                        [
                            "powershell", "-NoProfile", "-Command",
                            f"(Get-Item '{path}').VersionInfo.ProductVersion",
                        ],
                        stderr=subprocess.DEVNULL,
                    ).decode(errors="ignore").strip()
                    match = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
                    if match:
                        return int(match.group(1))
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue

    # 3) POSIX fallback (Linux/Mac) - original behaviour.
    for binary in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            out = subprocess.check_output([binary, "--version"], stderr=subprocess.DEVNULL).decode()
            return int(out.strip().split()[-1].split(".")[0])
        except (FileNotFoundError, ValueError, IndexError):
            continue

    return 0  # fall back to latest if detection fails


class Browser:
    __instance = None

    @staticmethod
    def get():
        # print("Browser.getBrowser() called")
        if Browser.__instance is None:
            with threading.Lock():
                if Browser.__instance is None:
                    # print("Creating new browser instance due to no instance found")
                    Browser.__instance = Browser()
        return Browser.__instance

    def __init__(self):
        if Browser.__instance is not None:
            raise Exception("This class is a singleton!")
        else:
            Browser.__instance = self
        self.user_agent = ""
        options = uc.ChromeOptions()
        # Proxies not supported on login.
        # if WITH_PROXIES:
        #     options.add_argument('--proxy-server={}'.format(PROXIES[0]))

        if USE_EXISTING_CHROME_PROFILE and CHROME_USER_DATA_DIR:
            os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)
            options.add_argument(f'--user-data-dir={CHROME_USER_DATA_DIR}')
            options.add_argument(f'--profile-directory={CHROME_PROFILE_DIRECTORY}')

        chrome_major = _get_chrome_major_version()
        try:
            self._driver = uc.Chrome(options=options, version_main=chrome_major)
        except Exception as e:
            if USE_EXISTING_CHROME_PROFILE:
                print(
                    "[-] Khong mo duoc Chrome voi profile rieng cua tool.\n"
                    "    Nguyen nhan thuong gap: co 1 tien trinh Chrome CU cua chinh tool nay\n"
                    "    (khong phai Chrome ca nhan) dang con chay ngam tu lan truoc chua thoat het.\n"
                    "    -> Mo Task Manager, tim tien trinh 'chrome.exe' co dong lenh chua\n"
                    f"       '{CHROME_USER_DATA_DIR}', tat no di, roi chay lai."
                )
            raise e

        self.with_random_user_agent()

    def with_random_user_agent(self, fallback=None):
        """Set random user agent.
        NOTE: This could fail with `FakeUserAgentError`.
        Provide `fallback` str to set the user agent to the provided string, in case it fails. 
        If fallback is not provided the exception is re-raised"""

        try:
            self.user_agent = UserAgent().random
        except FakeUserAgentError as e:
            if fallback:
                self.user_agent = fallback
            else:
                raise e

    @property
    def driver(self):
        return self._driver

    def load_cookies_from_file(self, filename):
        cookies = load_cookies_from_file(filename)
        for cookie in cookies:
            self._driver.add_cookie(cookie)
        self._driver.refresh()

    def save_cookies(self, filename: str, cookies:list=None):
        save_cookies_to_file(cookies, filename)


if __name__ == "__main__":
    import os
    # get current relative path of this file.
    print(os.path.dirname(os.path.abspath(__file__)))
