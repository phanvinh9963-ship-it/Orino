"""
core/voice_clone.py
NhÃ¢n báº£n giá»ng nÃ³i (voice cloning) báº±ng Coqui XTTS-v2 â€” vÃ  viXTTS cho tiáº¿ng Viá»‡t.

CHáº Y á»ž ÄÃ‚U:
Module nÃ y PHáº¢I cháº¡y trÃªn mÃ¡y cá»§a báº¡n (khÃ´ng cháº¡y Ä‘Æ°á»£c trong sandbox code nÃ y)
vÃ¬ cáº§n: (1) táº£i model ~2GB tá»« HuggingFace láº§n Ä‘áº§u, (2) lÃ½ tÆ°á»Ÿng cÃ³ GPU (CUDA)
Ä‘á»ƒ tá»‘c Ä‘á»™ cháº¥p nháº­n Ä‘Æ°á»£c - cháº¡y CPU váº«n Ä‘Æ°á»£c nhÆ°ng cháº­m (vÃ i chá»¥c giÃ¢y/cÃ¢u).

2 "biáº¿n thá»ƒ" model, Tá»° Äá»˜NG chá»n theo target_lang (khÃ´ng cáº§n cáº¥u hÃ¬nh gÃ¬ thÃªm):
  - "xtts_v2" : model Coqui XTTS-v2 gá»‘c, há»— trá»£ 17 ngÃ´n ngá»¯ (khÃ´ng cÃ³ tiáº¿ng Viá»‡t).
                DÃ¹ng cho má»i target_lang khÃ¡c "Vietnamese".
  - "vixtts"  : báº£n fine-tune cá»™ng Ä‘á»“ng (capleaf/viXTTS trÃªn HuggingFace) má»Ÿ
                rá»™ng tokenizer + train thÃªm cho tiáº¿ng Viá»‡t, dá»±a trÃªn Ä‘Ãºng kiáº¿n
                trÃºc XTTS-v2.0.3. DÃ¹ng Tá»° Äá»˜NG khi target_lang="Vietnamese".
                Load qua API cáº¥p tháº¥p (XttsConfig + Xtts) cá»§a cÃ¹ng gÃ³i
                coqui-tts Ä‘Ã£ cÃ i â€” KHÃ”NG cáº§n WSL2, cháº¡y Ä‘Æ°á»£c trÃªn Windows.
                Nguá»“n: https://huggingface.co/capleaf/viXTTS
                Ghi chÃº cá»§a tÃ¡c giáº£: cÃ¢u tiáº¿ng Viá»‡t dÆ°á»›i 10 tá»« cÃ³ thá»ƒ ra káº¿t
                quáº£ khÃ´ng á»•n Ä‘á»‹nh (thá»«a Ã¢m á»Ÿ cuá»‘i cÃ¢u) - nÃªn dÃ¹ng cÃ¢u Ä‘á»§ dÃ i.

CÃ€I Äáº¶T:
    pip install coqui-tts
(huggingface_hub vÃ  soundfile Ä‘Ã£ cÃ³ sáºµn vÃ¬ lÃ  dependency cá»§a transformers/coqui-tts)

GIáº¤Y PHÃ‰P (Báº®T BUá»˜C Äá»ŒC):
Cáº£ XTTS-v2 vÃ  viXTTS Ä‘á»u phÃ¡t hÃ nh theo giáº¥y phÃ©p Coqui Public Model License (CPML):
  - CHá»ˆ Ä‘Æ°á»£c dÃ¹ng phi thÆ°Æ¡ng máº¡i (non-commercial) trá»« khi báº¡n mua license riÃªng tá»« Coqui.
  - ToÃ n vÄƒn: https://coqui.ai/cpml
Model sáº½ yÃªu cáº§u báº¡n xÃ¡c nháº­n Ä‘á»“ng Ã½ license nÃ y á»Ÿ láº§n cháº¡y Ä‘áº§u tiÃªn.
CODE NÃ€Y KHÃ”NG Tá»° Äá»˜NG Äá»’NG Ã GIÃ™M Báº N â€” báº¡n pháº£i tá»± set biáº¿n mÃ´i trÆ°á»ng
COQUI_TOS_AGREED=1 SAU KHI Ä‘Ã£ tá»± Ä‘á»c vÃ  Ä‘á»“ng Ã½ license, xem hÃ m `check_license_consent()`.

Äáº O Äá»¨C:
Chá»‰ nhÃ¢n báº£n giá»ng cá»§a chÃ­nh báº¡n hoáº·c ngÆ°á»i Ä‘Ã£ Ä‘á»“ng Ã½ rÃµ rÃ ng. KhÃ´ng dÃ¹ng Ä‘á»ƒ
giáº£ giá»ng ngÆ°á»i khÃ¡c (lá»«a Ä‘áº£o, deepfake, máº¡o danh...).
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment
from core.voice_sample import VoiceProfile, load_voice_profile

LICENSE_URL = "https://coqui.ai/cpml"
LICENSE_ENV_VAR = "COQUI_TOS_AGREED"

VIXTTS_REPO_ID = "capleaf/viXTTS"
# 3 file nÃ y Báº®T BUá»˜C Ä‘á»ƒ cháº¡y clone báº±ng giá»ng tham chiáº¿u riÃªng (speaker_wav) cá»§a báº¡n.
VIXTTS_FILES = ["model.pth", "config.json", "vocab.json"]
# speakers_xtts.pth chá»‰ chá»©a embedding cá»§a cÃ¡c giá»ng demo cÃ³ sáºµn cá»§a repo (khÃ´ng dÃ¹ng
# tá»›i khi báº¡n tá»± truyá»n speaker_wav riÃªng) - táº£i náº¿u cÃ³, bá» qua náº¿u thiáº¿u/404.
VIXTTS_OPTIONAL_FILES = ["speakers_xtts.pth"]


class LicenseNotAcceptedError(RuntimeError):
    pass


def check_license_consent() -> None:
    """
    Kiá»ƒm tra ngÆ°á»i dÃ¹ng Ä‘Ã£ tá»± Ä‘á»“ng Ã½ license CPML hay chÆ°a (qua biáº¿n mÃ´i trÆ°á»ng).
    KHÃ”NG tá»± Ä‘á»™ng set biáº¿n nÃ y á»Ÿ Ä‘Ã¢u trong code â€” ngÆ°á»i dÃ¹ng pháº£i tá»± set sau khi Ä‘á»c license,
    vÃ­ dá»¥ trong terminal trÆ°á»›c khi cháº¡y:

        export COQUI_TOS_AGREED=1        # Linux/macOS
        set COQUI_TOS_AGREED=1           # Windows cmd
        $env:COQUI_TOS_AGREED=1          # Windows PowerShell

    Viá»‡c nÃ y Ä‘áº£m báº£o ngÆ°á»i dÃ¹ng THá»°C Sá»° biáº¿t vÃ  Ä‘á»“ng Ã½ Ä‘iá»u khoáº£n, thay vÃ¬ bá»‹
    code tá»± Ä‘á»™ng "báº¥m Ä‘á»“ng Ã½" ngáº§m.
    """
    if os.environ.get(LICENSE_ENV_VAR, "").strip() not in ("1", "true", "True"):
        raise LicenseNotAcceptedError(
            f"ChÆ°a xÃ¡c nháº­n Ä‘á»“ng Ã½ giáº¥y phÃ©p Coqui Public Model License (CPML).\n"
            f"Äá»c ká»¹ táº¡i: {LICENSE_URL}\n"
            f"(LÆ°u Ã½: license nÃ y CHá»ˆ cho phÃ©p dÃ¹ng PHI THÆ¯Æ NG Máº I, trá»« khi báº¡n mua license riÃªng.)\n"
            f"Náº¿u báº¡n Ä‘á»“ng Ã½, tá»± set biáº¿n mÃ´i trÆ°á»ng {LICENSE_ENV_VAR}=1 rá»“i cháº¡y láº¡i."
        )


_MODEL_CACHE = {}   # key: (model_variant, device) -> model object
_VIXTTS_CONFIG_CACHE = {}  # key: device -> XttsConfig object cá»§a viXTTS (cáº§n cho .synthesize())


def _select_model_variant(target_lang: str) -> str:
    """Tá»± Ä‘á»™ng chá»n biáº¿n thá»ƒ model theo ngÃ´n ngá»¯ Ä‘Ã­ch. Tiáº¿ng Viá»‡t -> viXTTS, cÃ²n láº¡i -> XTTS-v2 gá»‘c."""
    return "vixtts" if target_lang == "Vietnamese" else "xtts_v2"


def _download_vixtts(cache_dir: str, progress_cb: Optional[Callable[[float, str], None]] = None) -> str:
    """Táº£i cÃ¡c file cáº§n thiáº¿t cá»§a viXTTS tá»« HuggingFace (capleaf/viXTTS), cache láº¡i cho láº§n sau."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError

    os.makedirs(cache_dir, exist_ok=True)
    for i, fname in enumerate(VIXTTS_FILES, start=1):
        if progress_cb:
            progress_cb(0.0, f"Äang táº£i viXTTS ({i}/{len(VIXTTS_FILES)}): {fname}...")
        hf_hub_download(repo_id=VIXTTS_REPO_ID, filename=fname, local_dir=cache_dir)

    for fname in VIXTTS_OPTIONAL_FILES:
        try:
            hf_hub_download(repo_id=VIXTTS_REPO_ID, filename=fname, local_dir=cache_dir)
        except EntryNotFoundError:
            pass  # file tÃ¹y chá»n, khÃ´ng cÃ³ cÅ©ng khÃ´ng sao (chá»‰ dÃ¹ng cho giá»ng demo cÃ³ sáºµn)
    return cache_dir


def _normalize_vietnamese_text(txt: str) -> str:
    """
    Chuáº©n hoÃ¡ vÄƒn báº£n tiáº¿ng Viá»‡t trÆ°á»›c khi Ä‘Æ°a vÃ o tokenizer cá»§a XTTS/viXTTS:
    Ä‘á»c sá»‘, ngÃ y thÃ¡ng, Ä‘Æ¡n vá»‹... thÃ nh chá»¯ (vd: "12/2020" -> "thÃ¡ng mÆ°á»i hai nÄƒm
    hai nghÃ¬n khÃ´ng trÄƒm hai mÆ°Æ¡i"), Ä‘á»ƒ model khÃ´ng bá»‹ láº«n sá»‘/kÃ½ hiá»‡u khÃ´ng Ä‘á»c Ä‘Æ°á»£c.

    DÃ¹ng thÆ° viá»‡n thuáº§n Python `vietnormalizer` (khÃ´ng cáº§n biÃªn dá»‹ch C++, cháº¡y tá»‘t
    trÃªn Windows) thay vÃ¬ `vinorm` mÃ  báº£n demo gá»‘c cá»§a viXTTS dÃ¹ng (vinorm chá»‰ há»—
    trá»£ Linux). Náº¿u chÆ°a cÃ i `vietnormalizer`, fallback vá» chuáº©n hoÃ¡ khoáº£ng tráº¯ng
    cÆ¡ báº£n (cháº¥t lÆ°á»£ng Ä‘á»c sá»‘/ngÃ y thÃ¡ng sáº½ kÃ©m hÆ¡n, nhÆ°ng khÃ´ng cháº·n chÆ°Æ¡ng trÃ¬nh).
    """
    import re

    try:
        from vietnormalizer import VietnameseNormalizer
        normalizer = VietnameseNormalizer()
        txt = normalizer.normalize(txt)
    except ImportError:
        pass  # thiáº¿u vietnormalizer -> bá» qua bÆ°á»›c chuáº©n hoÃ¡ sá»‘/ngÃ y thÃ¡ng

    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _patch_tokenizer_for_vietnamese(tokenizer) -> None:
    """
    VÃ¡ method preprocess_text cá»§a tokenizer (instance Ä‘Ã£ load) Ä‘á»ƒ há»— trá»£ lang="vi".
    GÃ³i coqui-tts cÃ i qua pip chá»‰ láº­p trÃ¬nh cá»©ng cho 17 ngÃ´n ngá»¯ gá»‘c cá»§a XTTS-v2,
    dÃ¹ model viXTTS (qua config.json) Ä‘Ã£ khai bÃ¡o há»— trá»£ "vi" - nÃªn pháº£i vÃ¡ thÃªm á»Ÿ
    Ä‘Ã¢y, KHÃ”NG Ä‘á»¥ng vÃ o file cÃ i Ä‘áº·t cá»§a thÆ° viá»‡n (an toÃ n hÆ¡n khi update/reinstall).
    VÃ¡ trÃªn chÃ­nh class cá»§a instance, khÃ´ng cáº§n biáº¿t trÆ°á»›c tÃªn class chÃ­nh xÃ¡c.
    """
    cls = type(tokenizer)
    if getattr(cls, "_vi_patch_applied", False):
        return

    _original_preprocess_text = cls.preprocess_text

    def _patched_preprocess_text(self, txt, lang):
        if lang == "vi":
            return _normalize_vietnamese_text(txt)
        return _original_preprocess_text(self, txt, lang)

    cls.preprocess_text = _patched_preprocess_text
    cls._vi_patch_applied = True


def _load_model(device: str = "auto", model_variant: str = "xtts_v2",
                progress_cb: Optional[Callable[[float, str], None]] = None):
    """Load model XTTS-v2 hoáº·c viXTTS (cache láº¡i theo (variant, device) Ä‘á»ƒ khÃ´ng load láº¡i nhiá»u láº§n)."""
    check_license_consent()

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"

    key = (model_variant, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key], device

    if model_variant == "vixtts":
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts

        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "vixtts")
        needs_download = not all(
            os.path.exists(os.path.join(cache_dir, f)) for f in VIXTTS_FILES
        )
        if needs_download:
            if progress_cb:
                progress_cb(0.0, "Äang táº£i model viXTTS (~2GB, cáº§n internet, chá»‰ 1 láº§n)...")
            _download_vixtts(cache_dir, progress_cb)

        config = XttsConfig()
        config.load_json(os.path.join(cache_dir, "config.json"))
        model = Xtts.init_from_config(config)
        model.load_checkpoint(
            config,
            checkpoint_path=os.path.join(cache_dir, "model.pth"),
            vocab_path=os.path.join(cache_dir, "vocab.json"),
            use_deepspeed=False,
        )
        model.to(device)
        _patch_tokenizer_for_vietnamese(model.tokenizer)
        _VIXTTS_CONFIG_CACHE[device] = config
    else:
        from TTS.api import TTS  # package: coqui-tts

        model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    _MODEL_CACHE[key] = model
    return model, device


# MÃ£ ngÃ´n ngá»¯ há»— trá»£. XTTS-v2 gá»‘c khÃ´ng cÃ³ "vi" (tiáº¿ng Viá»‡t) - chá»‰ viXTTS má»›i cÃ³.
XTTS_LANG_CODE = {
    "English": "en", "Vietnamese": "vi", "Chinese": "zh-cn",
    "Japanese": "ja", "Korean": "ko", "French": "fr", "Spanish": "es",
}

# NgÃ´n ngá»¯ mÃ  XTTS-v2 Gá»C (khÃ´ng pháº£i viXTTS) thá»±c sá»± há»— trá»£ - dÃ¹ng Ä‘á»ƒ bÃ¡o lá»—i rÃµ rÃ ng sá»›m.
XTTS_V2_SUPPORTED_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi",
}


def clone_one(
    text: str,
    voice_profile: VoiceProfile,
    target_lang: str,
    out_path: str,
    device: str = "auto",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Táº¡o 1 cÃ¢u audio báº±ng giá»ng Ä‘Ã£ clone. Tráº£ vá» Ä‘Æ°á»ng dáº«n file wav.

    Tá»± Ä‘á»™ng chá»n model: target_lang="Vietnamese" -> viXTTS, cÃ²n láº¡i -> XTTS-v2 gá»‘c.
    """
    if not voice_profile.consent_confirmed:
        raise ValueError(
            f"Voice profile '{voice_profile.name}' chÆ°a Ä‘Æ°á»£c xÃ¡c nháº­n consent "
            f"(consent_confirmed=False). KhÃ´ng thá»ƒ dÃ¹ng Ä‘á»ƒ clone."
        )
    if not os.path.exists(voice_profile.reference_wav):
        raise FileNotFoundError(f"KhÃ´ng tÃ¬m tháº¥y file máº«u giá»ng: {voice_profile.reference_wav}")

    model_variant = _select_model_variant(target_lang)
    lang = XTTS_LANG_CODE.get(target_lang, "en")

    if model_variant == "xtts_v2" and lang not in XTTS_V2_SUPPORTED_LANGS:
        raise ValueError(
            f"NgÃ´n ngá»¯ '{target_lang}' ({lang}) khÃ´ng Ä‘Æ°á»£c XTTS-v2 há»— trá»£. "
            f"CÃ¡c ngÃ´n ngá»¯ há»— trá»£: {sorted(XTTS_V2_SUPPORTED_LANGS)}"
        )

    model, device = _load_model(device, model_variant, progress_cb=progress_cb)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if model_variant == "vixtts":
        import soundfile as sf

        config = _VIXTTS_CONFIG_CACHE[device]
        outputs = model.synthesize(
            text,
            config,
            speaker_wav=voice_profile.reference_wav,
            gpt_cond_len=6,
            language=lang,
        )
        sf.write(out_path, outputs["wav"], 24000)
    else:
        model.tts_to_file(
            text=text,
            speaker_wav=voice_profile.reference_wav,
            language=lang,
            file_path=out_path,
        )

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"XTTS khÃ´ng táº¡o Ä‘Æ°á»£c file audio cho cÃ¢u: {text!r}")
    return out_path


def synthesize_segments_cloned(
    segments: List[SubtitleSegment],
    target_lang: str,
    voice_name: str,
    profiles_dir: str,
    out_dir: str,
    device: str = "auto",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[str]:
    """
    Sinh audio lá»“ng tiáº¿ng cho toÃ n bá»™ segments báº±ng giá»ng Ä‘Ã£ clone (voice_name).
    TÆ°Æ¡ng Ä‘Æ°Æ¡ng core.tts.synthesize_segments nhÆ°ng dÃ¹ng XTTS-v2/viXTTS clone thay vÃ¬ edge-tts/pyttsx3.

    Tá»± Ä‘á»™ng dÃ¹ng viXTTS náº¿u target_lang="Vietnamese" (XTTS-v2 gá»‘c khÃ´ng há»— trá»£ tiáº¿ng Viá»‡t),
    cÃ²n láº¡i dÃ¹ng XTTS-v2 gá»‘c.

    KHÃ”NG cÃ³ fallback tá»± Ä‘á»™ng sang giá»ng khÃ¡c náº¿u clone lá»—i â€” vÃ¬ má»¥c Ä‘Ã­ch cá»§a
    tÃ­nh nÄƒng nÃ y lÃ  giá»¯ ÄÃšNG giá»ng cá»§a báº¡n xuyÃªn suá»‘t. Náº¿u 1 cÃ¢u lá»—i, pipeline
    sáº½ dá»«ng vÃ  bÃ¡o lá»—i rÃµ rÃ ng thay vÃ¬ Ã¢m tháº§m Ä‘á»•i sang giá»ng khÃ¡c (trÃ¡nh láº·p láº¡i
    Ä‘Ãºng lá»—i "xen káº½ giá»ng" Ä‘Ã£ gáº·p trÆ°á»›c Ä‘Ã¢y vá»›i edge-tts/pyttsx3).
    """
    check_license_consent()
    profile = load_voice_profile(profiles_dir, voice_name)
    if not profile.consent_confirmed:
        raise ValueError(f"Voice profile '{voice_name}' chÆ°a Ä‘Æ°á»£c xÃ¡c nháº­n consent.")

    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []
    total = max(1, len(segments))

    model_variant = _select_model_variant(target_lang)
    if progress_cb:
        model_label = "viXTTS (há»— trá»£ tiáº¿ng Viá»‡t)" if model_variant == "vixtts" else "XTTS-v2"
        progress_cb(0.0, f"Äang táº£i model {model_label} (thiáº¿t bá»‹: {device})... láº§n Ä‘áº§u cÃ³ thá»ƒ máº¥t vÃ i phÃºt")

    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip() or "..."
        out_path = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
        clone_one(text, profile, target_lang, out_path, device=device, progress_cb=progress_cb)
        paths.append(out_path)
        if progress_cb:
            progress_cb(i / total, f"Äang clone giá»ng cÃ¢u {i}/{total}")

    return paths
