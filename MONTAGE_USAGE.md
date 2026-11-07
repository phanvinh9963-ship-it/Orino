# MONTAGE_USAGE.md - Huong dan dung OpenMontage voi Reup Studio

## Luong su dung
1. Chay `F:\Orino\run_montage.bat` de kich hoat `.venv` va mo `opencode` tai thu muc OpenMontage.
2. Dat video goc + file SRT (neu co) vao `OpenMontage\exchange\input\`.
3. Yeu cau agent xu ly (vi du: "Dung video A thanh short 9:16, them phu de, xuat ra exchange\output").
4. Ket qua (video hau ky) xuat ra `OpenMontage\exchange\output\`.
5. Reup Studio tiep tuc tu file output do (khong import ma OpenMontage vao core).

## Vi du cau lenh cho agent (khong chay thu)
- "Doc OpenMontage\AGENTS.md va AGENTS.local.md, sau do xu ly file trong exchange\input\thu_nghiem.mp4 theo pipeline short-form."
- "Kiem tra provider_menu_summary() truoc khi bat dau."
- "Xuat ket qua vao exchange\output\final.mp4."

## Quy tac bat buoc
- Xac nhan bang van ban truoc khi render (human checkpoint: idea/proposal, script, scene_plan, assets, publish).
- Khong render video, khong goi API tra phi, khong nhap API key khi chua duoc phe duyet.
- AGPL-3.0: OpenMontage giu nguyen la thu muc rieng, KHONG merge ma vao core\ cua Reup Studio.
- OpenMontage ton token model: han che goi pipeline lon, uu tien test ngan.

## Luu y
- Reup Studio dung faster-whisper (core/transcribe.py L60) cho transcript va edge-tts (core/tts.py L118) / omnivoice cho TTS.
- OpenMontage dung Piper (piper-tts 1.8.0) trong .venv rieng.