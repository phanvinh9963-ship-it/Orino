"""
core/douyin_download.py
Táº£i video tá»« Douyin (Ä‘Æ¡n láº» hoáº·c HÃ€NG LOáº T tá»« 1 trang cÃ¡ nhÃ¢n/profile) vá» mÃ¡y,
dÃ¹ng thÆ° viá»‡n yt-dlp - dÃ¹ng lÃ m nguá»“n input Ä‘áº§u vÃ o cho pipeline dá»‹ch/lá»“ng
tiáº¿ng (core/pipeline.py).

Há»– TRá»¢ 2 Dáº NG LINK:
  - Link 1 video   : vd https://v.douyin.com/xxxxxxx/  hoáº·c
                      https://www.douyin.com/video/7xxxxxxxxxxxxxxxxx
  - Link trang cÃ¡ nhÃ¢n (profile/user), Táº¢I Táº¤T Cáº¢ video cá»§a ngÆ°á»i Ä‘Ã³:
                      vd https://www.douyin.com/user/MS4wLjABAAAA...
                      (yt-dlp coi Ä‘Ã¢y lÃ  1 "playlist" vÃ  tá»± liá»‡t kÃª háº¿t video)

CÃ€I Äáº¶T:
    pip install yt-dlp
Khuyáº¿n khÃ­ch luÃ´n dÃ¹ng báº£n yt-dlp Má»šI NHáº¤T (Douyin hay Ä‘á»•i cÆ¡ cháº¿ chá»‘ng bot,
báº£n cÅ© dá»… bá»‹ lá»—i "Unsupported URL" hoáº·c táº£i thiáº¿u):
    pip install -U yt-dlp

COOKIES (thÆ°á»ng Cáº¦N THIáº¾T vá»›i Douyin):
Douyin thÆ°á»ng cháº·n táº£i náº¿u khÃ´ng cÃ³ cookie Ä‘Äƒng nháº­p há»£p lá»‡ (Ä‘áº·c biá»‡t vá»›i
trang cÃ¡ nhÃ¢n riÃªng tÆ° hoáº·c bá»‹ giá»›i háº¡n). CÃ¡ch Ä‘Æ¡n giáº£n nháº¥t: Ä‘Äƒng nháº­p
douyin.com sáºµn trÃªn trÃ¬nh duyá»‡t (Chrome/Edge/Firefox...) rá»“i truyá»n
`cookies_from_browser="chrome"` (hoáº·c "edge", "firefox"...) - yt-dlp sáº½ tá»±
Ä‘á»c cookie tá»« Ä‘Ãºng trÃ¬nh duyá»‡t Ä‘Ã³, khÃ´ng cáº§n xuáº¥t file cookie thá»§ cÃ´ng.

GIá»šI Háº N Sá» LÆ¯á»¢NG:
Trang cÃ¡ nhÃ¢n cÃ³ thá»ƒ cÃ³ Ráº¤T NHIá»€U video - dÃ¹ng `max_videos` Ä‘á»ƒ giá»›i háº¡n (vd
chá»‰ táº£i 20 video má»›i nháº¥t) trÃ¡nh táº£i nháº§m hÃ ng trÄƒm video ngoÃ i Ã½ muá»‘n.

Äáº O Äá»¨C / PHÃP LÃ:
Chá»‰ táº£i video mÃ  báº¡n cÃ³ quyá»n sá»­ dá»¥ng (video cá»§a chÃ­nh báº¡n, hoáº·c Ä‘Ã£ Ä‘Æ°á»£c
phÃ©p rÃµ rÃ ng tá»« chá»§ sá»Ÿ há»¯u) Ä‘á»ƒ dá»‹ch/lá»“ng tiáº¿ng láº¡i. TÃ´n trá»ng báº£n quyá»n vÃ 
Ä‘iá»u khoáº£n sá»­ dá»¥ng cá»§a Douyin.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class DownloadedVideo:
    url: str            # link gá»‘c cá»§a video nÃ y trÃªn Douyin
    file_path: str       # Ä‘Æ°á»ng dáº«n file .mp4 Ä‘Ã£ táº£i vá»
    title: str = ""


@dataclass
class DouyinDownloadResult:
    videos: List[DownloadedVideo] = field(default_factory=list)
    failed: List[tuple] = field(default_factory=list)   # (url, lÃ½ do lá»—i cá»¥ thá»ƒ) - hiá»ƒn thá»‹ tháº³ng cho ngÆ°á»i dÃ¹ng, khÃ´ng giáº¥u lÃ½ do


def _is_probably_profile_link(url: str) -> bool:
    """Nháº­n biáº¿t sÆ¡ bá»™ link lÃ  trang cÃ¡ nhÃ¢n (nhiá»u video) hay 1 video láº» - chá»‰ Ä‘á»ƒ hiá»ƒn thá»‹ log rÃµ hÆ¡n,
    KHÃ”NG áº£nh hÆ°á»Ÿng tá»›i viá»‡c táº£i (yt-dlp tá»± xá»­ lÃ½ Ä‘Ãºng cáº£ 2 dáº¡ng)."""
    return "/user/" in url


def download_from_douyin(
    urls: List[str],
    out_dir: str,
    max_videos: Optional[int] = 20,
    cookies_from_browser: Optional[str] = None,   # "chrome" | "edge" | "firefox" | "brave" | "opera" | "vivaldi" | "safari"
    cookies_file: Optional[str] = None,             # Ä‘Æ°á»ng dáº«n file cookies.txt (netscape format), thay tháº¿ cho cookies_from_browser
    filename_template: str = "%(uploader)s - %(title).80s [%(id)s].%(ext)s",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> DouyinDownloadResult:
    """
    Táº£i vá» `out_dir` toÃ n bá»™ video á»©ng vá»›i danh sÃ¡ch `urls` (má»—i pháº§n tá»­ cÃ³ thá»ƒ
    lÃ  link 1 video HOáº¶C link trang cÃ¡ nhÃ¢n - yt-dlp tá»± nháº­n diá»‡n vÃ  liá»‡t kÃª
    háº¿t video náº¿u lÃ  trang cÃ¡ nhÃ¢n).

    max_videos: giá»›i háº¡n sá»‘ video Táº¢I Má»šI cho Má»–I link trang cÃ¡ nhÃ¢n (khÃ´ng Ã¡p
    dá»¥ng cho link 1 video láº»). None = khÃ´ng giá»›i háº¡n (cáº©n tháº­n náº¿u trang cÃ³
    hÃ ng trÄƒm video).

    Tráº£ vá» DouyinDownloadResult gá»“m danh sÃ¡ch video Ä‘Ã£ táº£i thÃ nh cÃ´ng (kÃ¨m
    Ä‘Æ°á»ng dáº«n file cá»¥ thá»ƒ) vÃ  danh sÃ¡ch url lá»—i (náº¿u cÃ³) - KHÃ”NG raise lá»—i
    giá»¯a chá»«ng Ä‘á»ƒ 1 video lá»—i khÃ´ng lÃ m há»ng cáº£ lÆ°á»£t táº£i hÃ ng loáº¡t.
    """
    try:
        import yt_dlp
    except ImportError as e:
        raise ImportError(
            "Cáº§n cÃ i Ä‘áº·t: pip install -U yt-dlp Ä‘á»ƒ dÃ¹ng tÃ­nh nÄƒng táº£i video tá»« Douyin."
        ) from e

    if not urls:
        raise ValueError("ChÆ°a cÃ³ link Douyin nÃ o Ä‘á»ƒ táº£i.")

    os.makedirs(out_dir, exist_ok=True)
    result = DouyinDownloadResult()

    total_urls = max(1, len(urls))
    # Äáº¿m sá»‘ video ÄÃƒ Táº¢I TRONG LÆ¯á»¢T NÃ€Y Ä‘á»ƒ yt-dlp Ã¡p giá»›i háº¡n max_videos cho tá»«ng link profile riÃªng biá»‡t
    for url_i, url in enumerate(urls, start=1):
        url = url.strip()
        if not url:
            continue

        kind = "trang cÃ¡ nhÃ¢n (nhiá»u video)" if _is_probably_profile_link(url) else "video láº»"
        if progress_cb:
            progress_cb((url_i - 1) / total_urls, f"Äang xá»­ lÃ½ link {url_i}/{total_urls} ({kind})...")

        downloaded_this_url: List[DownloadedVideo] = []

        def _hook(d, _url=url):
            if d.get("status") == "downloading":
                fn = os.path.basename(d.get("filename", ""))
                pct_str = d.get("_percent_str", "").strip()
                if progress_cb:
                    # dá»“n tiáº¿n Ä‘á»™ trong khoáº£ng cá»§a url hiá»‡n táº¡i Ä‘á»ƒ thanh progress tá»•ng khÃ´ng bá»‹ nháº£y lÃ¹i
                    base = (url_i - 1) / total_urls
                    span = 1.0 / total_urls
                    progress_cb(base + span * 0.5, f"Äang táº£i: {fn} ({pct_str})")
            elif d.get("status") == "finished":
                fp = d.get("filename", "")
                if fp and os.path.exists(fp):
                    downloaded_this_url.append(DownloadedVideo(url=_url, file_path=fp))

        ydl_opts = {
            "outtmpl": os.path.join(out_dir, filename_template),
            "format": "bv*+ba/b",   # Æ°u tiÃªn video+audio tá»‘t nháº¥t, fallback file gá»™p sáºµn náº¿u source khÃ´ng tÃ¡ch track
            "merge_output_format": "mp4",
            "progress_hooks": [_hook],
            "ignoreerrors": True,     # 1 video lá»—i trong playlist khÃ´ng dá»«ng cáº£ lÆ°á»£t táº£i
            "noplaylist": False,      # cho phÃ©p táº£i cáº£ playlist (trang cÃ¡ nhÃ¢n)
            "quiet": True,
            "no_warnings": True,
        }
        if max_videos is not None:
            ydl_opts["playlistend"] = max_videos   # chá»‰ Ã¡p dá»¥ng khi url lÃ  playlist/trang cÃ¡ nhÃ¢n
        if cookies_from_browser:
            ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
        elif cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            reason = str(e).strip() or type(e).__name__
            # Lá»—i phá»• biáº¿n trÃªn Windows: trÃ¬nh duyá»‡t Ä‘ang Má»ž khoÃ¡ file cookie SQLite,
            # yt-dlp khÃ´ng copy Ä‘Æ°á»£c Ä‘á»ƒ Ä‘á»c. Báº¯t Ä‘Ãºng theo text lá»—i tháº­t cá»§a yt-dlp
            # ("Could not copy Chrome cookie database...") thay vÃ¬ Ä‘oÃ¡n chung chung.
            reason_lower = reason.lower()
            is_cookie_lock_error = "cookie" in reason_lower and (
                "could not copy" in reason_lower
                or "permission" in reason_lower
                or "being used" in reason_lower
                or "locked" in reason_lower
            )
            # Tá»° Äá»˜NG THá»¬ Láº I khÃ´ng dÃ¹ng cookie trÆ°á»›c khi bÃ¡o lá»—i háº³n - ráº¥t nhiá»u video
            # Douyin cÃ´ng khai (khÃ´ng riÃªng tÆ°) váº«n táº£i Ä‘Æ°á»£c bÃ¬nh thÆ°á»ng mÃ  KHÃ”NG Cáº¦N
            # cookie, nÃªn lá»—i Ä‘á»c cookie khÃ´ng nháº¥t thiáº¿t lÃ m há»ng cáº£ lÆ°á»£t táº£i.
            if is_cookie_lock_error and (cookies_from_browser or cookies_file):
                if progress_cb:
                    progress_cb(url_i / total_urls, "âš  Lá»—i Ä‘á»c cookie trÃ¬nh duyá»‡t - Ä‘ang thá»­ láº¡i KHÃ”NG dÃ¹ng cookie...")
                retry_opts = dict(ydl_opts)
                retry_opts.pop("cookiesfrombrowser", None)
                retry_opts.pop("cookiefile", None)
                try:
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        ydl.download([url])
                    reason = None   # thá»­ láº¡i khÃ´ng cookie THÃ€NH CÃ”NG -> bá» qua pháº§n bÃ¡o lá»—i bÃªn dÆ°á»›i
                except Exception as e2:
                    reason = str(e2).strip() or type(e2).__name__
                    is_cookie_lock_error = False   # lá»—i láº§n 2 khÃ´ng pháº£i do cookie ná»¯a, khÃ´ng láº·p láº¡i gá»£i Ã½ cookie

            if reason is None:
                pass   # thá»­ láº¡i thÃ nh cÃ´ng, rÆ¡i tháº³ng xuá»‘ng Ä‘oáº¡n xá»­ lÃ½ downloaded_this_url bÃªn dÆ°á»›i
            else:
                if is_cookie_lock_error:
                    reason += (
                        "\n   -> ÄÃ£ tá»± thá»­ láº¡i khÃ´ng dÃ¹ng cookie nhÆ°ng váº«n cáº§n Ä‘Äƒng nháº­p. CÃ¡ch sá»­a lá»—i Ä‘á»c cookie Chrome: "
                        "(1) Táº®T Háº²N trÃ¬nh duyá»‡t (ká»ƒ cáº£ icon cháº¡y ngáº§m á»Ÿ khay há»‡ thá»‘ng, khÃ´ng chá»‰ Ä‘Ã³ng cá»­a sá»•), "
                        "rá»“i táº£i láº¡i - HOáº¶C (2) Ä‘á»•i 'Láº¥y cookie tá»« trÃ¬nh duyá»‡t' sang trÃ¬nh duyá»‡t khÃ¡c báº¡n khÃ´ng "
                        "Ä‘ang má»Ÿ (vd 'edge' hoáº·c 'firefox') - HOáº¶C (3) export cookies.txt thá»§ cÃ´ng báº±ng extension "
                        "'Get cookies.txt LOCALLY' rá»“i trá» vÃ o file Ä‘Ã³."
                    )
                result.failed.append((url, reason))
                if progress_cb:
                    progress_cb(url_i / total_urls, f"âœ• Lá»—i khi táº£i link {url_i}/{total_urls}: {reason}")
                continue

        if not downloaded_this_url:
            # KhÃ´ng cÃ³ file nÃ o -> coi nhÆ° lá»—i (vd link riÃªng tÆ°, cáº§n cookie, hoáº·c link sai)
            reason = "KhÃ´ng táº£i Ä‘Æ°á»£c video nÃ o (cÃ³ thá»ƒ video riÃªng tÆ°/bá»‹ giá»›i háº¡n - thá»­ báº­t cookie tá»« trÃ¬nh duyá»‡t)"
            result.failed.append((url, reason))
            if progress_cb:
                progress_cb(url_i / total_urls, f"âœ• Link {url_i}/{total_urls}: {reason}")
        else:
            result.videos.extend(downloaded_this_url)
            if progress_cb:
                progress_cb(url_i / total_urls, f"âœ“ Link {url_i}/{total_urls}: táº£i xong {len(downloaded_this_url)} video")

    if progress_cb:
        progress_cb(1.0, f"HoÃ n táº¥t: {len(result.videos)} video thÃ nh cÃ´ng, {len(result.failed)} link lá»—i")

    return result


_URL_RE = re.compile(r"https?://[^\s,ï¼Œã€ï¼ˆï¼‰()\[\]'\"]+")


def parse_urls_textbox(raw_text: str) -> List[str]:
    """
    TÃ¡ch cÃ¡c link Douyin THáº¬T tá»« ná»™i dung ngÆ°á»i dÃ¹ng dÃ¡n vÃ o Ã´ textbox.

    QUAN TRá»ŒNG: khi báº¥m "Chia sáº»" trÃªn app Douyin, nÃ³ copy ra Cáº¢ 1 CÃ‚U (link +
    lá»i hÆ°á»›ng dáº«n tiáº¿ng Trung dÃ­nh liá»n, vd:
      "https://v.douyin.com/xxxxx/ å¤åˆ¶æ­¤é“¾æŽ¥ï¼Œæ‰“å¼€DouéŸ³æœç´¢ï¼Œç›´æŽ¥è§‚çœ‹è§†é¢‘ï¼")
    CÃ¡ch tÃ¡ch cÅ© (chá»‰ split theo khoáº£ng tráº¯ng/dáº¥u pháº©y Ná»¬A-Äá»˜-Rá»˜NG) khÃ´ng tÃ¡ch
    Ä‘Æ°á»£c dáº¥u pháº©y TOÃ€N-Äá»˜-Rá»˜NG "ï¼Œ" trong cÃ¢u tiáº¿ng Trung, khiáº¿n cáº£ cÃ¢u Ä‘Ã³ bá»‹
    hiá»ƒu NHáº¦M thÃ nh 1 "link" riÃªng -> yt-dlp bÃ¡o lá»—i "Unsupported URL" cho cÃ¢u
    chá»¯ Ä‘Ã³ (khÃ´ng pháº£i link tháº­t nÃ o bá»‹ lá»—i cáº£).

    CÃ¡ch sá»­a: dÃ¹ng regex tÃ¬m ÄÃšNG cÃ¡c chuá»—i báº¯t Ä‘áº§u báº±ng http(s):// trong toÃ n
    bá»™ vÄƒn báº£n dÃ¡n vÃ o (báº¥t ká»ƒ cÃ³ chá»¯/cÃ¢u gÃ¬ bao quanh), sau Ä‘Ã³ lá»c láº¡i chá»‰ giá»¯
    nhá»¯ng chuá»—i cÃ³ chá»©a "douyin.com" - bá» háº¿t pháº§n chá»¯ chÃº thÃ­ch thá»«a, dÃ¹ ngÆ°á»i
    dÃ¹ng dÃ¡n nguyÃªn cáº£ tin nháº¯n chia sáº» hay chá»‰ dÃ¡n má»—i link.
    """
    if not raw_text:
        return []
    urls: List[str] = []
    seen = set()
    for m in _URL_RE.findall(raw_text):
        u = m.rstrip(".,;:!?ï¼Ÿï¼ã€‚ã€ã€ã€\"')]}")   # bá» dáº¥u cÃ¢u dÃ­nh á»Ÿ cuá»‘i do ngÆ°á»i dÃ¹ng copy nguyÃªn cáº£ cÃ¢u
        if "douyin.com" not in u:
            continue   # khÃ´ng pháº£i link Douyin (vd link khÃ¡c láº«n vÃ o, hoáº·c rÃ¡c) -> bá» qua thay vÃ¬ coi lÃ  lá»—i
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls

