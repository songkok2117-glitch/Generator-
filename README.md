# AI Prompt Generator Pro (Gemini API)

Aplikasi web responsif untuk Android/desktop. Frontend disajikan oleh FastAPI dan backend memanggil Gemini. API key hanya berada di environment server, tidak ditanam di `index.html`.

## Fitur

- **Image to Prompt**: analisis subjek, elemen sekunder, lingkungan, pencahayaan, sudut kamera, depth of field, tekstur, mood, color grading, style, prompt Inggris minimal 80 kata, dan JSON.
- **Video to Prompt**: unggah video, deteksi durasi, pecah timeline menjadi segmen 10 detik (termasuk segmen akhir yang lebih pendek), ekstrak dua keyframe per segmen di server, lalu minta Gemini menganalisis gerak dan kontinuitas sinematik.
- Pilihan rasio aspek dan gaya prompt.
- Copy output, unduh TXT dan JSON.
- Batas default: gambar 15 MB; video 250 MB dan 10 menit.

## 1. Siapkan Gemini API key

1. Buka [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Login dengan akun Google dan buat API key.
3. Salin API key. Jangan kirim key ke orang lain dan jangan masukkan key ke file HTML.
4. Periksa ketersediaan model di [Gemini API Models](https://ai.google.dev/gemini-api/docs/models). Default proyek adalah `gemini-3.8-flash`; jika tidak tersedia untuk akun/region Anda, ubah `GEMINI_MODEL` ke model Flash yang tersedia.

Penggunaan API dapat dikenakan biaya/kuota sesuai akun Google AI Studio. Periksa billing dan rate limits sebelum mengunggah video besar.

## 2. Cara termudah dari Android: deploy sebagai website

Ini cara yang paling disarankan karena Android hanya perlu browser; Python dan OpenCV berjalan di server.

1. Unduh dan ekstrak ZIP proyek ini.
2. Buat repository baru di [GitHub](https://github.com/new), misalnya `ai-prompt-generator-pro`.
3. Upload semua isi folder proyek ke repository (pastikan `main.py`, `requirements.txt`, `Procfile`, dan folder `static` berada di root repository).
4. Buka [Render](https://render.com/) dan login.
5. Pilih **New + → Web Service**, lalu hubungkan repository GitHub.
6. Isi pengaturan:
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
7. Di bagian **Environment**, tambahkan:
   - Key: `GEMINI_API_KEY`
   - Value: API key dari Google AI Studio
   - Key: `GEMINI_MODEL`
   - Value: `gemini-3.8-flash` (atau model Flash yang tersedia untuk akun Anda)
8. Klik **Create Web Service** dan tunggu proses build/deploy selesai.
9. Buka URL HTTPS Render yang diberikan. Gunakan Chrome Android untuk membuka aplikasi.

Catatan: paket gratis hosting dapat tidur saat tidak digunakan, memiliki batas CPU/memori, dan tidak cocok untuk video sangat besar. Untuk penggunaan rutin, pilih instance sesuai kebutuhan.

## 3. Jalankan lokal (komputer)

Butuh Python 3.10+ dan koneksi internet.

```bash
# 1. Ekstrak ZIP lalu masuk ke folder proyek
cd ai_prompt_generator_pro

# 2. Buat virtual environment (opsional tetapi disarankan)
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Instal dependency
pip install -r requirements.txt

# 4. Atur API key (Linux/macOS)
export GEMINI_API_KEY="PASTE_API_KEY_ANDA"
# Windows PowerShell:
$env:GEMINI_API_KEY="PASTE_API_KEY_ANDA"

# 5. Jalankan server
uvicorn main:app --host 0.0.0.0 --port 8000
```

Buka `http://127.0.0.1:8000`. Untuk akses dari Android di Wi-Fi yang sama, buka `http://IP-KOMPUTER:8000` (gunakan IP lokal komputer, dan izinkan port 8000 di firewall).

## 4. Menjalankan langsung di Android dengan Termux (opsional)

Instal Termux dari sumber resminya. Ketersediaan wheel OpenCV/Python bisa berbeda antarperangkat Android, sehingga metode hosting di atas lebih mudah dan stabil.

```bash
pkg update && pkg upgrade
pkg install python git
```

Salin folder proyek ke penyimpanan Termux, lalu:

```bash
cd /path/ke/ai_prompt_generator_pro
pip install -r requirements.txt
export GEMINI_API_KEY="PASTE_API_KEY_ANDA"
uvicorn main:app --host 127.0.0.1 --port 8000
```

Buka `http://127.0.0.1:8000` di Chrome Android. Jika instalasi `opencv-python-headless` gagal di perangkat, gunakan deploy hosting atau jalankan backend di komputer.

## 5. Tes backend

Setelah server aktif, buka:

- `https://ALAMAT-WEBSITE/health`

Respons normal terlihat seperti:

```json
{
  "ok": true,
  "model": "gemini-3.8-flash",
  "api_key_configured": true
}
```

`api_key_configured: false` berarti environment variable belum diatur dengan benar. Jangan pernah menguji dengan menempelkan API key ke chat atau halaman web.

## Cara kerja mode video

Browser mengirim video ke backend. Backend:
1. Membaca durasi dan FPS video.
2. Menghitung segmen 10 detik, termasuk segmen terakhir yang kurang dari 8 detik.
3. Mengekstrak dua keyframe representatif per segmen.
4. Mengunggah video melalui Gemini Files API dan menunggu file siap diproses.
5. Mengirim video + keyframe + instruksi segmentasi ke Gemini.
6. Mengembalikan prompt umum, prompt mandiri per segmen, timestamps, analisis visual dan catatan kontinuitas.

Dua keyframe adalah sampel representatif, bukan jaminan menangkap setiap kejadian dalam segmen. Untuk adegan yang sangat cepat, hasil AI dapat melewatkan detail kecil.

## Troubleshooting

- **503 – GEMINI_API_KEY belum diatur**: atur `GEMINI_API_KEY` di Environment hosting, lalu restart/redeploy.
- **400 – format tidak valid**: coba JPG/PNG untuk gambar atau MP4 H.264 untuk video.
- **413 – file terlalu besar/panjang**: kecilkan file. Batas dapat diubah di konstanta `MAX_IMAGE_BYTES`, `MAX_VIDEO_BYTES`, `MAX_VIDEO_SECONDS` pada `main.py`.
- **502 – Gemini gagal**: cek kuota, billing, nama model, koneksi server, dan log aplikasi di hosting.
- **504 – pemrosesan video melewati batas waktu**: coba video yang lebih pendek atau deploy server dengan resource lebih besar.
- **Tidak bisa diakses dari HP**: gunakan URL HTTPS dari hosting, bukan `localhost` milik komputer/server lain.

## Keamanan

- Jangan commit file `.env` atau membagikan API key.
- Jangan menaruh Gemini API key di JavaScript/frontend.
- Untuk aplikasi publik, tambahkan autentikasi, pembatasan request per pengguna, dan proteksi biaya sebelum membagikan URL secara luas.
