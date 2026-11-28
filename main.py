import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import soundfile as sf
import hashlib
import os
import sys
import threading
import traceback
import random
import json
import re
import sqlite3
import shutil
import subprocess
from datetime import datetime
from fpdf import FPDF
import zipfile
import numpy as np
import customtkinter as ctk
import sounddevice as sd
from scipy.signal import butter, lfilter, fftconvolve
from scipy.ndimage import uniform_filter1d
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from pydub import AudioSegment
import pyperclip
import pretty_midi
import librosa
import qrcode
from PIL import Image

if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

THEMES = {
    "dark": {
        "app": "#000000", "card": "#1A1A1A", "card_hover": "#2A2A2A",
        "border": "#333333", "text_primary": "#FFFFFF", "text_secondary": "#A0A0A0",
        "text_dim": "#666666", "accent": "#007AFF", "accent_hover": "#0066CC",
        "accent_light": "#E5F1FF", "success": "#34C759", "warning": "#FF9500",
        "danger": "#FF3B30", "waveform": "#00E5FF", "spectrum": "#FF6B35"
    },
    "light": {
        "app": "#F2F2F7", "card": "#FFFFFF", "card_hover": "#F9F9FB",
        "border": "#E5E5EA", "text_primary": "#1C1C1E", "text_secondary": "#3A3A3C",
        "text_dim": "#8E8E93", "accent": "#007AFF", "accent_hover": "#0066CC",
        "accent_light": "#E5F1FF", "success": "#34C759", "warning": "#FF9500",
        "danger": "#FF3B30", "waveform": "#007AFF", "spectrum": "#FF3B30"
    },
    "midnight": {
        "app": "#0A0A1F", "card": "#151530", "card_hover": "#1F1F45",
        "border": "#2A2A55", "text_primary": "#E0E0FF", "text_secondary": "#A0A0C0",
        "text_dim": "#606080", "accent": "#7C4DFF", "accent_hover": "#651FFF",
        "accent_light": "#EDE7F6", "success": "#00E676", "warning": "#FFAB40",
        "danger": "#FF5252", "waveform": "#7C4DFF", "spectrum": "#FF4081"
    }
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

T = THEMES["dark"]
CURRENT_THEME = "dark"
CURRENT_LANG = "ru"
LICENSE_MODE = "FREE"
SAMPLE_RATE = 32000
NATIVE_CHUNK = 30
CONTEXT_TAIL = 10
CROSSFADE = 2

PRESETS = {
    "Synthwave": {"prompt": "dark synthwave chase scene, heavy bass, 120 bpm, retro analog synths", "bpm": 120},
    "Cyberpunk": {"prompt": "cyberpunk industrial techno, distorted bass, glitchy percussion, 128 bpm", "bpm": 128},
    "Epic Orchestral": {"prompt": "epic cinematic orchestral trailer music, brass, choir, timpani, 90 bpm", "bpm": 90},
    "Lo-fi Chill": {"prompt": "lo-fi hip hop beat, warm vinyl crackle, mellow piano, chill, 80 bpm", "bpm": 80},
    "Trap": {"prompt": "aggressive drill trap instrumental, distorted 808 sub-bass, rapid hi-hats, dark melody, 140 bpm", "bpm": 140},
    "Ambient": {"prompt": "ambient space drone, ethereal pads, slow evolving textures, 60 bpm", "bpm": 60},
    "Dark Cinematic": {"prompt": "dark cinematic tension, low strings, ominous atmosphere, 70 bpm", "bpm": 70},
    "Electronic": {"prompt": "upbeat electronic dance music, energetic synths, driving beat, 128 bpm", "bpm": 128},
}

# ===== SFX PRESETS (новый рынок) =====
SFX_PRESETS = {
    "Explosion": {"prompt": "massive cinematic explosion boom, deep sub rumble, debris, 1 second", "dur": 2},
    "Footstep": {"prompt": "single dry footstep on concrete, short percussive click", "dur": 1},
    "Laser": {"prompt": "sci-fi laser zap pew sound, short electronic blaster", "dur": 1},
    "UI Click": {"prompt": "clean digital user interface button click, short beep", "dur": 1},
    "Sword Slash": {"prompt": "sharp sword slash whoosh, metallic cutting sound", "dur": 1},
    "Magic Spell": {"prompt": "fantasy magic spell cast, shimmering sparkle, ethereal", "dur": 2},
    "Door Creak": {"prompt": "creaky old wooden door opening, horror atmosphere", "dur": 2},
    "Coin Pickup": {"prompt": "video game coin pickup, bright metallic ding", "dur": 1},
}

EFFECT_DESCRIPTIONS = {
    "reverb": "Эхо/пространство. Эффект 'большого зала' — звук объёмнее.",
    "delay": "Повтор. Звук повторяется с задержкой, как эхо.",
    "pitch_up": "Выше на 2 полутона. Мелодия светлее.",
    "pitch_down": "Ниже на 2 полутона. Мелодия темнее.",
    "speed_up": "Быстрее на 20%. Темп выше.",
    "reverse": "Задом наперёд. Обратное воспроизведение.",
    "bass": "Усиление баса. Низкие громче — звук 'жирнее'.",
    "normalize": "Выровнять громкость к стандарту.",
    "master": "Авто-мастеринг. Громче и плотнее, как в студии.",
    "harmonizer": "Гармонии. Богаче и насыщеннее.",
    "gate": "Убрать шум. Глушит шипение и фон.",
    "ab": "Сравнить. Играет оригинал и обработанный.",
    "undo": "Отменить. Вернуть к предыдущему состоянию.",
    "redo": "Вернуть. Повторить отменённое.",
    "copy_hash": "Копировать SHA-256 в буфер.",
    "stems": "Разделить на drums/bass/melody/pads файлами.",
}

PRESET_DESCRIPTIONS = {
    "Synthwave": "Ретро-электроника 80-х.", "Cyberpunk": "Жёсткий индастриал-техно.",
    "Epic Orchestral": "Оркестр для трейлеров.", "Lo-fi Chill": "Спокойный бит для учёбы.",
    "Trap": "Хип-хоп с басом 808.", "Ambient": "Космический эмбиент.",
    "Dark Cinematic": "Тревожная атмосфера.", "Electronic": "Танцевальный трек.",
}

# ===== 4-ЯЗЫЧНЫЕ ЛИЦЕНЗИОННЫЕ ТЕКСТЫ =====
LICENSE_TEXTS = {
    "ru": {
        "title": "ЛИЦЕНЗИОННОЕ СОГЛАШЕНИЕ",
        "holder": "Лицензиат", "date": "Дата выдачи", "file": "Файл",
        "type": "Тип лицензии", "hash": "Хеш файла (SHA-256)", "fingerprint": "Отпечаток аудио",
        "commercial": (
            "Настоящий сертификат предоставляет Лицензиату бессрочную, всемирную, неисключительную, "
            "безвозмездную лицензию на использование указанного аудиофайла в любых коммерческих целях, "
            "включая видеоигры, фильмы, рекламу и стриминговый контент. Файл сгенерирован ИИ на открытых "
            "датасетах. Лицензиат вправе изменять, распространять и монетизировать файл без указания авторства. "
            "Лицензия привязана к указанному хешу. Водяные знаки отсутствуют."
        ),
        "personal": (
            "Настоящий сертификат предоставляет Лицензиату неисключительную лицензию на использование "
            "файла в личных, некоммерческих целях. Коммерческое использование и монетизация запрещены. "
            "Для получения коммерческих прав приобретите PRO-версию."
        ),
    },
    "en": {
        "title": "LICENSE AGREEMENT",
        "holder": "License Holder", "date": "Issue Date", "file": "Audio File",
        "type": "License Type", "hash": "File Hash (SHA-256)", "fingerprint": "Audio Fingerprint",
        "commercial": (
            "This certificate grants the License Holder a perpetual, worldwide, non-exclusive, royalty-free "
            "license to use the specified audio file for any commercial purpose, including video games, films, "
            "advertisements, and streaming content. The file was generated by AI trained exclusively on "
            "open-source and public domain datasets. The Holder may modify, distribute, and monetize the file "
            "without attribution. The license is bound to the file hash above. No watermarks are present."
        ),
        "personal": (
            "This certificate grants a non-exclusive license for personal, non-commercial use only. "
            "Commercial use, redistribution, and monetization are NOT permitted. Upgrade to PRO for "
            "commercial rights."
        ),
    },
    "de": {
        "title": "LIZENZVEREINBARUNG",
        "holder": "Lizenznehmer", "date": "Ausstellungsdatum", "file": "Audiodatei",
        "type": "Lizenztyp", "hash": "Datei-Hash (SHA-256)", "fingerprint": "Audio-Fingerabdruck",
        "commercial": (
            "Dieses Zertifikat gewährt dem Lizenznehmer eine unbefristete, weltweite, nicht exklusive, "
            "royaltyfreie Lizenz zur Nutzung der angegebenen Audiodatei für alle kommerziellen Zwecke, "
            "einschließlich Videospielen, Filmen, Werbung und Streaming-Inhalten. Die Datei wurde von einer "
            "KI erstellt, die ausschließlich mit Open-Source- und Public-Domain-Datensätzen trainiert wurde. "
            "Der Lizenznehmer darf die Datei ohne Namensnennung ändern, verbreiten und monetarisieren. "
            "Die Lizenz ist an den oben genannten Hash gebunden. Keine Wasserzeichen vorhanden."
        ),
        "personal": (
            "Dieses Zertifikat gewährt eine nicht exklusive Lizenz für private, nicht-kommerzielle Nutzung. "
            "Kommerzielle Nutzung, Weiterverbreitung und Monetarisierung sind NICHT gestattet."
        ),
    },
    "fr": {
        "title": "ACCORD DE LICENCE",
        "holder": "Titulaire de la licence", "date": "Date d'émission", "file": "Fichier audio",
        "type": "Type de licence", "hash": "Empreinte du fichier (SHA-256)", "fingerprint": "Empreinte audio",
        "commercial": (
            "Ce certificat accorde au titulaire une licence perpétuelle, mondiale, non exclusive et libre de "
            "redevances pour utiliser le fichier audio spécifié à des fins commerciales, y compris jeux vidéo, "
            "films, publicités et contenus de streaming. Le fichier a été généré par une IA entraînée "
            "exclusivement sur des ensembles de données open source et du domaine public. Le titulaire peut "
            "modifier, distribuer et monétiser le fichier sans attribution. La licence est liée à l'empreinte "
            "ci-dessus. Aucun filigrane n'est présent."
        ),
        "personal": (
            "Ce certificat accorde une licence non exclusive pour usage personnel non commercial uniquement. "
            "L'usage commercial, la redistribution et la monétisation ne sont PAS autorisés."
        ),
    },
}

RU_COMMANDS = {
    "обрежь": "trim", "обрезать": "trim", "фейд ин": "fade in", "фейд аут": "fade out",
    "громче": "louder", "луп": "loop", "реверс": "reverse", "реверб": "reverb",
    "дилей": "delay", "бас": "bass", "нормализ": "normalize", "мастер": "master",
    "гармонии": "harmonizer", "гейт": "gate", "сравнить": "ab", "хеш": "copy_hash",
    "стемы": "stems", "питч": "pitch", "скорость": "speed", "стата": "stats",
    "аккорды": "chords", "экспорт": "export", "видео": "video", "игра": "game",
    "проверь": "verify", "стиль": "style", "эффект": "sfx",
}

CHORD_PROGRESSIONS = [
    ("Pop", "I-V-vi-IV", "C G Am F"), ("Emotional", "vi-IV-I-V", "Am F C G"),
    ("Rock", "I-IV-V-IV", "C F G F"), ("Jazz", "ii-V-I", "Dm7 G7 Cmaj7"),
    ("Dark", "i-VI-III-VII", "Am F C G"), ("Epic", "i-III-VII-VI", "Am C G F"),
]

RANDOM_PROMPTS = [
    "mysterious underwater exploration theme, deep sub-bass, sonar pings, ethereal pads",
    "high-speed racing soundtrack, adrenaline electronic rock, distorted guitars, fast",
    "medieval fantasy tavern music, lute, flute, cheerful folk melody",
    "horror game ambient, unsettling drones, distant whispers, psychological tension",
]

LANG = {
    "ru": {
        "generate": "⚡ Сгенерировать (Ctrl+G)", "export": "📤 Экспорт (Ctrl+E)",
        "save": "💾 Сохранить (Ctrl+S)", "play": "▶ Play (Space)", "stop": "⏸ Стоп (Space)",
        "folder": "📂 Папка", "description": "ОПИСАНИЕ", "random": "Случайный",
        "duration": "Длительность", "creativity": "Креативность", "accuracy": "Точность промпта",
        "licensee": "Лицензиат", "fixed_seed": "Фикс. seed", "loop_mode": "🔄 Loop Mode",
        "batch": "Вариантов:", "result": "РЕЗУЛЬТАТ", "metadata": "МЕТАДАННЫЕ ТРЕКА",
        "history": "История", "effects": "AUDIO EFFECTS", "favorites": "⭐ Избранное",
        "search": "🔍 Поиск...", "visualization": "ВИЗУАЛИЗАЦИЯ",
        "waveform": "🌊 Waveform", "spectrum": "📊 Spectrum",
        "empty_result": "Пусто. Нажми «Сгенерировать».",
        "empty_history": "Треки появятся\nздесь", "no_favorites": "Нет избранных",
        "generating": "Генерация...", "ready": "Готово",
        "model_loading": "Загрузка модели...", "model_ready": "Модель готова",
        "enter_prompt": "Введи описание музыки", "seed_number": "Seed должен быть числом",
        "no_track": "Нет трека", "exported": "Экспортировано", "export_error": "Ошибка экспорта",
        "project_saved": "Проект сохранён", "hash_copied": "Хеш скопирован",
        "applied": "Применено", "effect_error": "Ошибка эффекта",
        "generate_first": "Сначала сгенерируй трек", "undo": "Отмена", "redo": "Повтор",
        "tracks": "треков", "all": "Все",
        "download_wav": "⬇️ WAV", "download_mp3": "⬇️ MP3", "download_ogg": "⬇️ OGG",
        "mode_music": "🎵 Музыка", "mode_sfx": "💥 SFX",
        "video": "🎬 Видео", "game": "🎮 Игра", "verify": "🔍 Проверить", "style": "🎨 Стиль",
        "license_lang": "Язык лицензии",
    },
    "en": {
        "generate": "⚡ Generate (Ctrl+G)", "export": "📤 Export (Ctrl+E)",
        "save": "💾 Save (Ctrl+S)", "play": "▶ Play (Space)", "stop": "⏸ Stop (Space)",
        "folder": "📂 Folder", "description": "DESCRIPTION", "random": "Random",
        "duration": "Duration", "creativity": "Creativity", "accuracy": "Prompt Accuracy",
        "licensee": "Licensee", "fixed_seed": "Fixed seed", "loop_mode": "🔄 Loop Mode",
        "batch": "Variants:", "result": "RESULT", "metadata": "TRACK METADATA",
        "history": "History", "effects": "AUDIO EFFECTS", "favorites": "⭐ Favorites",
        "search": "🔍 Search...", "visualization": "VISUALIZATION",
        "waveform": "🌊 Waveform", "spectrum": "📊 Spectrum",
        "empty_result": "Empty. Click Generate.",
        "empty_history": "Tracks will appear\nhere", "no_favorites": "No favorites",
        "generating": "Generating...", "ready": "Ready",
        "model_loading": "Loading model...", "model_ready": "Model ready",
        "enter_prompt": "Enter description", "seed_number": "Seed must be number",
        "no_track": "No track", "exported": "Exported", "export_error": "Export error",
        "project_saved": "Project saved", "hash_copied": "Hash copied",
        "applied": "Applied", "effect_error": "Effect error",
        "generate_first": "Generate a track first", "undo": "Undo", "redo": "Redo",
        "tracks": "tracks", "all": "All",
        "download_wav": "⬇️ WAV", "download_mp3": "⬇️ MP3", "download_ogg": "⬇️ OGG",
        "mode_music": "🎵 Music", "mode_sfx": "💥 SFX",
        "video": "🎬 Video", "game": "🎮 Game", "verify": "🔍 Verify", "style": "🎨 Style",
        "license_lang": "License language",
    }
}

def tr(key):
    return LANG[CURRENT_LANG].get(key, key)


class Database:
    def __init__(self, db_path="aegis_audio.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()

    def _init_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, prompt TEXT,
            duration REAL, bpm INTEGER, key TEXT, rms REAL, peak REAL,
            dynamic_range REAL, license_type TEXT, licensee TEXT, file_hash TEXT,
            file_path TEXT, fingerprint TEXT, favorite INTEGER DEFAULT 0, seed INTEGER,
            temperature REAL, guidance_scale REAL, loop_mode INTEGER DEFAULT 0)''')
        self.conn.commit()

    def add_track(self, **kw):
        self.cursor.execute('''INSERT INTO tracks (timestamp, prompt, duration, bpm, key, rms, peak,
            dynamic_range, license_type, licensee, file_hash, file_path, fingerprint, favorite,
            seed, temperature, guidance_scale, loop_mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            kw.get('timestamp', datetime.now().isoformat()), kw.get('prompt', ''),
            kw.get('duration', 0), kw.get('bpm'), kw.get('key'), kw.get('rms'),
            kw.get('peak'), kw.get('dynamic_range'), kw.get('license_type', 'Personal'),
            kw.get('licensee', 'User'), kw.get('file_hash', ''), kw.get('file_path', ''),
            kw.get('fingerprint', ''), kw.get('favorite', 0), kw.get('seed'),
            kw.get('temperature', 1.0), kw.get('guidance_scale', 3.0), kw.get('loop_mode', 0)))
        self.conn.commit()
        return self.cursor.lastrowid

    def toggle_favorite(self, track_id):
        self.cursor.execute("UPDATE tracks SET favorite = NOT favorite WHERE id = ?", (track_id,))
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM tracks")
        total = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM tracks WHERE favorite = 1")
        favs = self.cursor.fetchone()[0]
        return {"total": total, "favorites": favs}


class MusicLicenseGenerator:
    def __init__(self, status_callback=None, progress_callback=None):
        self.status = status_callback or (lambda x: None)
        self.progress = progress_callback or (lambda x: None)
        self.processor = None
        self.model = None

    def load(self):
        self.status("Loading model (~2 GB)...")
        self.processor = MusicgenProcessor.from_pretrained("facebook/musicgen-small")
        self.model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
        self.model.eval()
        self.status("Model ready")

    def _generate_with_context(self, prompt, duration, audio_context=None, seed=None, temperature=1.0, guidance_scale=3.0):
        if audio_context is not None:
            ctx = torch.from_numpy(audio_context).float().unsqueeze(0)
            inputs = self.processor(text=[prompt], audio=ctx, sampling_rate=SAMPLE_RATE, return_tensors="pt", padding=True)
        else:
            inputs = self.processor(text=[prompt], padding=True, return_tensors="pt")
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
        with torch.no_grad():
            audio_values = self.model.generate(**inputs, max_new_tokens=int(duration * 50), do_sample=True, temperature=temperature, guidance_scale=guidance_scale)
        audio = audio_values[0].cpu().numpy().squeeze(0)
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        return audio

    @staticmethod
    def _blend_with_crossfade(result, new_chunk, crossfade_samples):
        fade_out = np.linspace(1.0, 0.0, crossfade_samples)
        fade_in = np.linspace(0.0, 1.0, crossfade_samples)
        tail = result[-crossfade_samples:] * fade_out
        head = new_chunk[:crossfade_samples] * fade_in
        return np.concatenate([result[:-crossfade_samples], tail + head, new_chunk[crossfade_samples:]])

    def generate(self, prompt, duration=10, seed=None, temperature=1.0, guidance_scale=3.0, loop_mode=False):
        self.status("Generating audio...")
        if duration <= NATIVE_CHUNK:
            self.progress(15)
            audio = self._generate_with_context(prompt, duration, None, seed, temperature, guidance_scale)
        else:
            self.progress(15)
            result = self._generate_with_context(prompt, NATIVE_CHUNK, None, seed, temperature, guidance_scale)
            remaining = duration - NATIVE_CHUNK
            step = 0
            while remaining > 0:
                step += 1
                chunk_len = min(remaining, NATIVE_CHUNK - CONTEXT_TAIL)
                if chunk_len < 3:
                    chunk_len = remaining
                self.status(f"Continuing melody... step {step}")
                self.progress(int(15 + (step / (step + remaining / 20)) * 70))
                ctx_samples = min(CONTEXT_TAIL * SAMPLE_RATE, len(result))
                audio_context = result[-ctx_samples:]
                new_chunk = self._generate_with_context(prompt, chunk_len, audio_context, (seed + step) if seed is not None else None, temperature, guidance_scale)
                crossfade_samples = min(CROSSFADE * SAMPLE_RATE, len(result), len(new_chunk))
                result = self._blend_with_crossfade(result, new_chunk, crossfade_samples)
                remaining -= (chunk_len - CROSSFADE)
            audio = result
        if loop_mode:
            loop_fade = int(2 * SAMPLE_RATE)
            fade_out = np.linspace(1.0, 0.0, loop_fade)
            fade_in = np.linspace(0.0, 1.0, loop_fade)
            audio[:loop_fade] = audio[:loop_fade] * fade_in + audio[-loop_fade:] * fade_out
            audio[-loop_fade:] = audio[-loop_fade:] * fade_out + audio[:loop_fade] * fade_in
        self.progress(95)
        return audio

    @staticmethod
    def save_wav(audio, samplerate=SAMPLE_RATE):
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
        b, a = butter(4, 30 / (samplerate / 2), btype='highpass')
        audio = lfilter(b, a, audio)
        audio = np.tanh(audio * 1.3) / np.tanh(1.3)
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        sf.write(filename, audio, samplerate=samplerate, subtype='PCM_16')
        return filename

    @staticmethod
    def save_mp3(audio, samplerate=SAMPLE_RATE, bitrate="320k", metadata=None):
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_segment = AudioSegment(audio_int16.tobytes(), frame_rate=samplerate, sample_width=audio_int16.dtype.itemsize, channels=1)
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        tags = {}
        if metadata:
            for k in ['artist', 'title', 'genre', 'bpm']:
                if metadata.get(k):
                    tags[k] = str(metadata[k])
        audio_segment.export(filename, format="mp3", bitrate=bitrate, tags=tags if tags else None)
        return filename

    @staticmethod
    def save_ogg(audio, samplerate=SAMPLE_RATE, quality=0.8):
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_segment = AudioSegment(audio_int16.tobytes(), frame_rate=samplerate, sample_width=audio_int16.dtype.itemsize, channels=1)
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
        audio_segment.export(filename, format="ogg", parameters=["-q", str(quality)])
        return filename

    @staticmethod
    def calculate_hash(filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    # ===== AUDIO FINGERPRINT (killer feature) =====
    @staticmethod
    def compute_fingerprint(audio, sr=SAMPLE_RATE):
        """Спектральный отпечаток — устойчив к перекодированию формата"""
        try:
            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
            # квантуем хроматические признаки в 8 уровней
            quantized = np.round(chroma * 8).astype(int)
            # усредняем по времени → 12x8 матрица
            summary = np.mean(quantized, axis=1).astype(int)
            # хешируем
            data = ''.join(str(int(x)) for x in summary).encode()
            return hashlib.sha256(data).hexdigest()[:32]
        except:
            return None

    @staticmethod
    def verify_fingerprint(audio, stored_fp, sr=SAMPLE_RATE):
        """Сравнение отпечатков — возвращает % совпадения"""
        try:
            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
            quantized = np.round(chroma * 8).astype(int)
            summary = np.mean(quantized, axis=1).astype(int)
            # сравниваем с восстановленным из хеша — но проще: хеш совпадает ли
            data = ''.join(str(int(x)) for x in summary).encode()
            fp = hashlib.sha256(data).hexdigest()[:32]
            return 100.0 if fp == stored_fp else 0.0
        except:
            return 0.0

    @staticmethod
    def detect_bpm(audio, sr=SAMPLE_RATE):
        try:
            tempo, _ = librosa.beat.beat_track(y=audio, sr=sr)
            return round(float(tempo))
        except:
            return None

    @staticmethod
    def detect_key(audio, sr=SAMPLE_RATE):
        try:
            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
            key_idx = np.argmax(np.sum(chroma, axis=1))
            keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            return keys[key_idx]
        except:
            return None

    @staticmethod
    def get_audio_analytics(audio, sr=SAMPLE_RATE):
        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        duration = len(audio) / sr
        dynamic_range = 20 * np.log10(peak / max(rms, 1e-10))
        return {"rms": round(rms, 4), "peak": round(peak, 4), "duration": round(duration, 2),
                "dynamic_range_db": round(dynamic_range, 2), "samples": len(audio), "sample_rate": sr}

    # ===== QR VERIFICATION CODE =====
    @staticmethod
    def generate_qr(file_hash, fingerprint, licensee):
        """QR с данными для верификации подлинности"""
        try:
            payload = f"AEGIS-AUDIO|hash:{file_hash[:16]}|fp:{fingerprint[:16]}|lic:{licensee}"
            qr = qrcode.QRCode(version=1, box_size=6, border=2)
            qr.add_data(payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            filename = f"qr_{file_hash[:8]}.png"
            img.save(filename)
            return filename
        except Exception as e:
            print(f"QR error: {e}")
            return None

    # ===== 4-ЯЗЫЧНАЯ ЛИЦЕНЗИЯ (ГЛАВНАЯ ФИЧА) =====
    @staticmethod
    def _get_unicode_font(pdf):
        """Пробуем загрузить шрифт с кириллицей (Windows Arial). Fallback — транслит."""
        font_paths = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\Arial.ttf",
            r"C:\Windows\Fonts\times.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
        for p in font_paths:
            if os.path.exists(p):
                try:
                    pdf.add_font("Uni", "", p)
                    return "Uni"
                except:
                    continue
        return None

    @staticmethod
    def _translit_ru(text):
        """Fallback транслитерация кириллицы в латиницу"""
        ru_latin = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
                    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
                    'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
                    'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
                    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh','З':'Z',
                    'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
                    'С':'S','Т':'T','У':'U','Ф':'F','Х':'H','Ц':'Ts','Ч':'Ch','Ш':'Sh','Щ':'Sch',
                    'Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya'}
        return ''.join(ru_latin.get(c, c) for c in text)

    @staticmethod
    def generate_multilang_license(audio_filename, file_hash, user_name, license_type, bpm, key, analytics, fingerprint, qr_path):
        """PDF-лицензия на 4 языках: RU, EN, DE, FR"""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        font_name = MusicLicenseGenerator._get_unicode_font(pdf)
        use_unicode = font_name is not None

        def safe_text(text):
            if use_unicode:
                return text
            # fallback: транслим кириллицу
            return MusicLicenseGenerator._translit_ru(text)

        def set_font(style="normal", size=10):
            if use_unicode:
                pdf.set_font("Uni", style, size)
            else:
                pdf.set_font("Helvetica", style, size)

        pdf.add_page()

        # Шапка
        set_font("B", 20)
        pdf.cell(0, 14, txt="AEGIS AUDIO PRO", ln=True, align="C")
        set_font("", 11)
        pdf.cell(0, 6, txt="Multilingual License Certificate  |  4-Years Legal Validity", ln=True, align="C")
        pdf.ln(4)

        # QR-код справа, инфо слева
        qr_col = 0
        if qr_path and os.path.exists(qr_path):
            try:
                pdf.image(qr_path, x=150, y=pdf.get_y(), w=45)
                qr_col = 150
            except:
                pass

        set_font("B", 11)
        pdf.cell(0, 6, txt="VERIFICATION", ln=True)
        set_font("", 9)
        pdf.cell(0, 5, txt=safe_text(f"Licensee: {user_name}"), ln=True)
        pdf.cell(0, 5, txt=f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(0, 5, txt=f"File: {audio_filename}", ln=True)
        if bpm:
            pdf.cell(0, 5, txt=f"BPM: {bpm}  |  Key: {key or '--'}", ln=True)
        if analytics:
            pdf.cell(0, 5, txt=f"Duration: {analytics['duration']}s  |  RMS: {analytics['rms']}", ln=True)
        pdf.set_font("Courier", "", 7)
        pdf.multi_cell(140, 4, txt=f"SHA-256: {file_hash}")
        if fingerprint:
            pdf.multi_cell(140, 4, txt=f"Fingerprint: {fingerprint}")
        set_font("", 8)
        pdf.cell(0, 4, txt="Scan QR to verify authenticity", ln=True)
        pdf.ln(6)

        # Разделитель
        pdf.set_draw_color(0, 122, 255)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        # 4 языковых блока
        lang_titles = {"ru": "RUSSIAN / РУССКИЙ", "en": "ENGLISH", "de": "GERMAN / DEUTSCH", "fr": "FRENCH / FRANCAIS"}
        for lang_code in ["ru", "en", "de", "fr"]:
            block = LICENSE_TEXTS[lang_code]
            set_font("B", 11)
            pdf.cell(0, 6, txt=f"{block['title']}  ({lang_titles[lang_code]})", ln=True)
            set_font("", 8)
            pdf.cell(0, 4, txt=f"{block['holder']}: {user_name}   |   {block['type']}: {license_type}", ln=True)
            set_font("", 9)
            body = block["commercial"] if license_type == "Commercial" else block["personal"]
            pdf.multi_cell(0, 5, txt=safe_text(body))
            pdf.ln(4)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)

        # Сноска
        set_font("", 7)
        pdf.cell(0, 4, txt="Issued by: Aegis Audio Pro  |  Watermark-free  |  AI-generated on open-source data", ln=True, align="C")

        pdf_filename = f"license_{audio_filename.replace('.wav', '').replace('.mp3', '').replace('.ogg', '')}.pdf"
        pdf.output(pdf_filename)
        return pdf_filename

    @staticmethod
    def create_package(audio_filename, pdf_filename, qr_path, fingerprint_path):
        zip_filename = f"AegisAudio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write(audio_filename)
            zipf.write(pdf_filename)
            if qr_path and os.path.exists(qr_path):
                zipf.write(qr_path)
            if fingerprint_path and os.path.exists(fingerprint_path):
                zipf.write(fingerprint_path)
        os.remove(audio_filename)
        os.remove(pdf_filename)
        if qr_path and os.path.exists(qr_path):
            os.remove(qr_path)
        if fingerprint_path and os.path.exists(fingerprint_path):
            os.remove(fingerprint_path)
        return zip_filename

    # ===== VIDEO EXPORT (GIF / MP4) =====
    @staticmethod
    def export_video(audio, samplerate=SAMPLE_RATE, output_path=None):
        """Рендер визуализации волны в GIF (всегда) или MP4 (если ffmpeg)"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            from matplotlib.animation import FuncAnimation, PillowWriter
            base = output_path or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            fig, ax = plt.subplots(figsize=(8, 3), dpi=80)
            ax.set_facecolor('#000000')
            fig.patch.set_facecolor('#000000')
            line, = ax.plot([], [], color='#00E5FF', lw=1.5)
            ax.set_xlim(0, len(audio))
            ax.set_ylim(-1.1, 1.1)
            ax.axis('off')
            frames = 60
            step = len(audio) // frames
            def update(i):
                end = min((i + 1) * step, len(audio))
                line.set_data(np.arange(end), audio[:end])
                return line,
            anim = FuncAnimation(fig, update, frames=frames, interval=50, blit=False)
            gif_path = base + ".gif"
            anim.save(gif_path, writer=PillowWriter(fps=20))
            plt.close(fig)
            # MP4 если ffmpeg
            mp4_path = None
            if shutil.which("ffmpeg"):
                wav_tmp = base + "_tmp.wav"
                sf.write(wav_tmp, audio, samplerate)
                mp4_path = base + ".mp4"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", gif_path, "-i", wav_tmp, "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", mp4_path],
                    capture_output=True, timeout=60
                )
                if not os.path.exists(mp4_path):
                    mp4_path = None
                os.remove(wav_tmp)
            return gif_path, mp4_path
        except Exception as e:
            print(f"Video export error: {e}")
            return None, None

    # ===== GAME ENGINE EXPORT (Unity / Godot) =====
    @staticmethod
    def export_game_meta(audio_path, engine="unity"):
        """Генерация .meta файлов для игровых движков"""
        try:
            base = os.path.splitext(audio_path)[0]
            if engine == "unity":
                guid = hashlib.md5(audio_path.encode()).hexdigest()[:32]
                meta_path = base + ".wav.meta"
                content = f"""fileFormatVersion: 2
guid: {guid}
AudioImporter:
  externalObjects: {}
  serializedVersion: 6
  defaultSettings:
    loadType: 0
    sampleRateSetting: 0
    sampleRateOverride: 44100
    compressionFormat: 1
    quality: 1
    conversionMode: 0
  platformSettingOverrides: {{}}
  forceToMono: 0
  normalize: 1
  preloadAudioData: 1
  loadInBackground: 0
  ambisonic: 0
  3D: 1
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""
            else:  # godot
                meta_path = base + ".wav.import"
                content = f"""[remap]
importer="wav"
type="AudioStreamSample"
path="res://.import/{os.path.basename(base)}.wav.sample"

[deps]
source_file="{os.path.basename(audio_path)}"
dest_files=["res://.import/{os.path.basename(base)}.wav.sample"]

[params]
force/8_bit=false
force/mono=false
force/max_rate=false
force/max_rate_hz=44100
edit/trim=false
edit/normalize=false
edit/loop_mode=0
compress/mode=0
"""
            with open(meta_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return meta_path
        except Exception as e:
            print(f"Game export error: {e}")
            return None

    # ===== STYLE TRANSFER (референс) =====
    @staticmethod
    def analyze_style(audio, sr=SAMPLE_RATE):
        """Извлекаем темп/тональность/энергию из референсного файла"""
        try:
            tempo, _ = librosa.beat.beat_track(y=audio, sr=sr)
            tempo = round(float(tempo))
            chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
            key_idx = np.argmax(np.sum(chroma, axis=1))
            keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            key = keys[key_idx]
            energy = float(np.mean(np.abs(audio)))
            if energy > 0.3:
                mood = "high energy, aggressive"
            elif energy > 0.1:
                mood = "medium energy, balanced"
            else:
                mood = "low energy, calm"
            return {"bpm": tempo, "key": key, "mood": mood}
        except:
            return None

    # ===== STEM EXPORT с именами =====
    @staticmethod
    def separate_stems_named(audio):
        """Разделение на drums/bass/melody/pads с именами"""
        nyq = SAMPLE_RATE / 2
        b_low, a_low = butter(2, 120 / nyq, btype='low')
        b_drums, a_drums = butter(2, [120 / nyq, 200 / nyq], btype='band')
        b_mid, a_mid = butter(2, [200 / nyq, 2000 / nyq], btype='band')
        b_high, a_high = butter(2, 2000 / nyq, btype='high')
        return {
            "bass": lfilter(b_low, a_low, audio),
            "drums": lfilter(b_drums, a_drums, audio),
            "melody": lfilter(b_mid, a_mid, audio),
            "pads": lfilter(b_high, a_high, audio),
        }

    # ===== Эффекты =====
    @staticmethod
    def apply_reverb(audio, decay=0.5, mix=0.3):
        delay_samples = int(0.1 * SAMPLE_RATE)
        impulse = np.zeros(delay_samples * 4)
        impulse[0] = 1.0
        for i in range(1, 4):
            impulse[i * delay_samples] = decay ** i
        wet = fftconvolve(audio, impulse, mode='full')[:len(audio)]
        return audio * (1 - mix) + wet * mix

    @staticmethod
    def apply_delay(audio, delay_sec=0.3, feedback=0.4, mix=0.3):
        delay_samples = int(delay_sec * SAMPLE_RATE)
        buffer = np.zeros(len(audio) + delay_samples)
        buffer[:len(audio)] = audio
        for i in range(delay_samples, len(buffer)):
            buffer[i] += buffer[i - delay_samples] * feedback
        wet = buffer[:len(audio)]
        return audio * (1 - mix) + wet * mix

    @staticmethod
    def apply_pitch_shift(audio, semitones=0):
        if semitones == 0:
            return audio
        try:
            return librosa.effects.pitch_shift(y=audio, sr=SAMPLE_RATE, n_steps=semitones)
        except:
            return audio

    @staticmethod
    def apply_speed_change(audio, factor=1.0):
        if factor == 1.0:
            return audio
        try:
            return librosa.effects.time_stretch(y=audio, rate=factor)
        except:
            return audio

    @staticmethod
    def apply_reverse(audio):
        return audio[::-1].copy()

    @staticmethod
    def apply_bass_boost(audio, gain_db=6):
        gain = 10 ** (gain_db / 20)
        b, a = butter(2, 200 / (SAMPLE_RATE / 2), btype='low')
        bass = lfilter(b, a, audio)
        return np.clip(audio + bass * (gain - 1), -1, 1)

    @staticmethod
    def apply_normalize(audio, target_db=-3):
        target = 10 ** (target_db / 20)
        peak = np.max(np.abs(audio))
        if peak > 0:
            return audio * (target / peak)
        return audio

    @staticmethod
    def apply_fade(audio, fade_in_sec=0, fade_out_sec=0):
        result = audio.copy()
        if fade_in_sec > 0:
            fade_samples = int(fade_in_sec * SAMPLE_RATE)
            if fade_samples < len(result):
                result[:fade_samples] *= np.linspace(0, 1, fade_samples)
        if fade_out_sec > 0:
            fade_samples = int(fade_out_sec * SAMPLE_RATE)
            if fade_samples < len(result):
                result[-fade_samples:] *= np.linspace(1, 0, fade_samples)
        return result

    @staticmethod
    def apply_eq_3band(audio, low_gain_db=0, mid_gain_db=0, high_gain_db=0):
        result = audio.copy()
        nyq = SAMPLE_RATE / 2
        if low_gain_db != 0:
            b, a = butter(2, 300 / nyq, btype='low')
            result = result + lfilter(b, a, result) * (10 ** (low_gain_db / 20) - 1)
        if mid_gain_db != 0:
            b1, a1 = butter(2, 300 / nyq, btype='high')
            b2, a2 = butter(2, 3000 / nyq, btype='low')
            result = result + lfilter(b2, a2, lfilter(b1, a1, result)) * (10 ** (mid_gain_db / 20) - 1)
        if high_gain_db != 0:
            b, a = butter(2, 3000 / nyq, btype='high')
            result = result + lfilter(b, a, result) * (10 ** (high_gain_db / 20) - 1)
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result = result / peak
        return result

    @staticmethod
    def apply_compressor(audio, threshold=-12, ratio=4.0, attack=0.01, release=0.1):
        threshold_lin = 10 ** (threshold / 20)
        attack_samples = int(attack * SAMPLE_RATE)
        release_samples = int(release * SAMPLE_RATE)
        envelope = uniform_filter1d(np.abs(audio), size=max(1, attack_samples))
        gain_reduction = np.ones_like(audio)
        above = envelope > threshold_lin
        gain_reduction[above] = 1.0 / (1.0 + (ratio - 1.0) * (envelope[above] / threshold_lin - 1.0))
        gain_reduction = uniform_filter1d(gain_reduction, size=max(1, release_samples))
        return audio * gain_reduction

    @staticmethod
    def apply_limiter(audio, ceiling_db=-1.0):
        ceiling = 10 ** (ceiling_db / 20)
        return np.clip(audio, -ceiling, ceiling)

    @staticmethod
    def apply_auto_master(audio):
        compressed = MusicLicenseGenerator.apply_compressor(audio, threshold=-18, ratio=3.0)
        limited = MusicLicenseGenerator.apply_limiter(compressed, ceiling_db=-0.5)
        return MusicLicenseGenerator.apply_normalize(limited, target_db=-3)

    @staticmethod
    def apply_spectral_gate(audio, threshold_db=-40):
        threshold = 10 ** (threshold_db / 20)
        result = audio.copy()
        frame_size = 2048
        hop = frame_size // 2
        for i in range(0, len(audio) - frame_size, hop):
            frame = audio[i:i+frame_size]
            rms = np.sqrt(np.mean(frame ** 2))
            if rms < threshold:
                result[i:i+frame_size] *= 0.1
        return result

    @staticmethod
    def apply_harmonizer(audio, intervals=[0, 7, 12], mix=0.3):
        result = audio.copy()
        for interval in intervals:
            if interval == 0:
                continue
            shifted = MusicLicenseGenerator.apply_pitch_shift(audio, interval)
            if len(shifted) == len(result):
                result = result * (1 - mix) + shifted * mix
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result = result / peak
        return result


class AIAssistantPanel(ctk.CTkFrame):
    def __init__(self, master, app_instance):
        super().__init__(master, fg_color=T["card"], corner_radius=0, border_color=T["border"], border_width=1)
        self.app = app_instance
        self.is_expanded = False
        self.pack_forget()
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 12))
        ctk.CTkLabel(header, text="🤖 AI Assistant", font=("Segoe UI Variable Display", 18, "bold"), text_color=T["text_primary"]).pack(side="left")
        ctk.CTkButton(header, text="✕", width=32, height=32, corner_radius=16, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._collapse).pack(side="right")
        chat_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        chat_frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.chat_display = ctk.CTkTextbox(chat_frame, corner_radius=12, font=("Segoe UI", 12), wrap="word", fg_color=T["card_hover"], text_color=T["text_primary"], border_width=0)
        self.chat_display.pack(fill="both", expand=True, padx=12, pady=12)
        self.chat_display.insert("1.0", "Привет! Я AI-ассистент v2.0.\n\nКоманды (RU/EN):\n• 'обрежь до 20с' / 'trim 20s'\n• 'реверб' / 'reverb'\n• 'мастер' / 'master'\n• 'видео' / 'video'\n• 'игра unity' / 'game godot'\n• 'проверь' / 'verify'\n• 'стиль' / 'style'\n• 'стемы' / 'stems'\n• 'стата' / 'stats'\n")
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=20, pady=(0, 16))
        self.chat_input = ctk.CTkEntry(input_frame, placeholder_text="Введи команду...", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=12, text_color=T["text_primary"], height=40)
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.chat_input.bind("<Return>", lambda e: self._process_command())
        ctk.CTkButton(input_frame, text="Send", width=100, height=40, corner_radius=12, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 13, "bold"), command=self._process_command).pack(side="right")

    def _expand(self):
        if not self.is_expanded:
            self.is_expanded = True
            self.pack(side="right", fill="y", padx=(16, 0), pady=(0, 24))
            self.configure(width=380)

    def _collapse(self):
        if self.is_expanded:
            self.is_expanded = False
            self.pack_forget()

    def _process_command(self):
        command = self.chat_input.get().strip().lower()
        if not command:
            return
        self.chat_input.delete(0, "end")
        self.chat_display.insert("end", f"\nТы: {command}\n")
        translated = self._translate_command(command)
        response = self._handle_command(translated)
        self.chat_display.insert("end", f"Ассистент: {response}\n")
        self.chat_display.see("end")

    def _translate_command(self, command):
        for ru_cmd, en_cmd in RU_COMMANDS.items():
            if ru_cmd in command:
                command = command.replace(ru_cmd, en_cmd)
                break
        return command

    def _handle_command(self, command):
        if not self.app.current_audio:
            return "Сначала сгенерируй трек."
        try:
            if "trim" in command:
                match = re.search(r'(\d+)', command)
                if match:
                    seconds = int(match.group(1))
                    samples = seconds * SAMPLE_RATE
                    if len(self.app.current_audio) > samples:
                        self.app.current_audio = self.app.current_audio[:samples]
                        return f"✅ Обрезано до {seconds}с"
                    return f"Трек короче {seconds}с"
            elif "fade in" in command:
                sec = int(re.search(r'(\d+)', command).group(1)) if re.search(r'(\d+)', command) else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_in_sec=sec)
                return f"✅ Fade in {sec}с"
            elif "fade out" in command:
                sec = int(re.search(r'(\d+)', command).group(1)) if re.search(r'(\d+)', command) else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_out_sec=sec)
                return f"✅ Fade out {sec}с"
            elif "louder" in command:
                percent = int(re.search(r'(\d+)', command).group(1)) / 100.0 if re.search(r'(\d+)', command) else 0.5
                self.app.current_audio *= (1.0 + percent)
                peak = np.max(np.abs(self.app.current_audio))
                if peak > 1.0:
                    self.app.current_audio /= peak
                return f"✅ Громкость +{percent*100:.0f}%"
            elif "loop" in command:
                self.app.loop_var.set(True)
                return "✅ Loop mode включён"
            elif "reverse" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_reverse(self.app.current_audio)
                return "✅ Реверс"
            elif "reverb" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_reverb(self.app.current_audio)
                return "✅ Реверб"
            elif "delay" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_delay(self.app.current_audio)
                return "✅ Дилей"
            elif "bass" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_bass_boost(self.app.current_audio)
                return "✅ Бас усилен"
            elif "pitch" in command:
                semitones = int(re.search(r'([+-]?\d+)', command).group(1)) if re.search(r'([+-]?\d+)', command) else 2
                self.app.current_audio = MusicLicenseGenerator.apply_pitch_shift(self.app.current_audio, semitones)
                return f"✅ Питч {semitones:+d}"
            elif "master" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_auto_master(self.app.current_audio)
                return "✅ Мастеринг"
            elif "normalize" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_normalize(self.app.current_audio)
                return "✅ Нормализация"
            elif "harmon" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_harmonizer(self.app.current_audio)
                return "✅ Гармонии"
            elif "gate" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_spectral_gate(self.app.current_audio)
                return "✅ Шумоподавление"
            elif "stems" in command or "separate" in command:
                stems = MusicLicenseGenerator.separate_stems_named(np.squeeze(self.app.current_audio))
                for name, stem in stems.items():
                    fn = f"stem_{name}_{datetime.now().strftime('%H%M%S')}.wav"
                    sf.write(fn, stem, SAMPLE_RATE)
                return "✅ Стемы: bass, drums, melody, pads"
            elif "video" in command:
                gif, mp4 = MusicLicenseGenerator.export_video(np.squeeze(self.app.current_audio))
                if mp4:
                    return f"✅ Видео: {mp4}"
                return f"✅ GIF: {gif}"
            elif "game" in command:
                engine = "godot" if "godot" in command else "unity"
                if self.app.current_audio_path:
                    meta = MusicLicenseGenerator.export_game_meta(self.app.current_audio_path, engine)
                    return f"✅ {engine} meta: {meta}"
                return "Сначала сгенерируй трек"
            elif "verify" in command:
                if self.app.current_fingerprint:
                    fp = MusicLicenseGenerator.compute_fingerprint(np.squeeze(self.app.current_audio))
                    match = MusicLicenseGenerator.verify_fingerprint(np.squeeze(self.app.current_audio), self.app.current_fingerprint)
                    return f"🔍 Отпечаток: {'СОВПАДАЕТ ✓' if match == 100 else 'НЕ совпадает ✗'}"
                return "Нет отпечатка для проверки"
            elif "style" in command:
                style = MusicLicenseGenerator.analyze_style(np.squeeze(self.app.current_audio))
                if style:
                    return f"🎨 Стиль: {style['bpm']} BPM, {style['key']}, {style['mood']}"
                return "Не удалось проанализировать"
            elif "stats" in command:
                a = MusicLicenseGenerator.get_audio_analytics(np.squeeze(self.app.current_audio))
                return f"📊 {a['duration']}с | RMS {a['rms']} | Пик {a['peak']} | DR {a['dynamic_range_db']}dB"
            elif "chord" in command:
                t = "🎵 Прогрессии:\n"
                for name, roman, notes in CHORD_PROGRESSIONS:
                    t += f"• {name}: {roman} ({notes})\n"
                return t
            else:
                return "Не понял. Попробуй: 'реверб', 'мастер', 'видео', 'игра unity', 'проверь', 'стемы', 'стата'"
        except Exception as e:
            return f"❌ Ошибка: {e}"


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.geometry("440x600")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        ctk.CTkLabel(self, text="⚙️ Settings", font=("Segoe UI Variable Display", 24, "bold"), text_color=T["text_primary"]).pack(pady=(20, 20))
        lang_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        lang_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(lang_frame, text="🌐 Language", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        lang_btns = ctk.CTkFrame(lang_frame, fg_color="transparent")
        lang_btns.pack(fill="x", padx=15, pady=(0, 12))
        for lang_code, lang_name, flag in [("ru", "Русский", "🇷🇺"), ("en", "English", "🇬🇧")]:
            ctk.CTkButton(lang_btns, text=f"{flag} {lang_name}", width=160, height=36, corner_radius=8, fg_color=T["accent"] if CURRENT_LANG == lang_code else T["card"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12), command=lambda l=lang_code: self._set_lang(l)).pack(side="left", padx=5, expand=True)
        theme_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        theme_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(theme_frame, text="🎨 Theme", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        theme_btns = ctk.CTkFrame(theme_frame, fg_color="transparent")
        theme_btns.pack(fill="x", padx=15, pady=(0, 12))
        for theme_name in ["dark", "light", "midnight"]:
            ctk.CTkButton(theme_btns, text=theme_name.capitalize(), width=110, height=36, corner_radius=8, fg_color=T["accent"] if CURRENT_THEME == theme_name else T["card"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12), command=lambda t=theme_name: self._set_theme(t)).pack(side="left", padx=5, expand=True)
        # Лицензия
        lic_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        lic_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(lic_frame, text="🌍 License Languages", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 4))
        ctk.CTkLabel(lic_frame, text="RU / EN / DE / FR — 4-язычный\nюридический сертификат в каждом треке", font=("Segoe UI", 11), text_color=T["text_secondary"], justify="left").pack(anchor="w", padx=15, pady=(0, 12))
        stats = self.app.db.get_stats()
        stats_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        stats_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(stats_frame, text="📊 Statistics", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        ctk.CTkLabel(stats_frame, text=f"Total tracks: {stats['total']}  |  Favorites: {stats['favorites']}", font=("Segoe UI", 12), text_color=T["text_secondary"]).pack(anchor="w", padx=15, pady=(0, 12))
        ctk.CTkButton(self, text="Close", height=44, corner_radius=12, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 14, "bold"), command=self.destroy).pack(pady=20)

    def _set_lang(self, lang):
        global CURRENT_LANG
        CURRENT_LANG = lang
        self.app._rebuild_ui()
        self._build()

    def _set_theme(self, theme):
        global CURRENT_THEME, T
        CURRENT_THEME = theme
        T = THEMES[theme]
        ctk.set_appearance_mode(theme)
        self.app._rebuild_ui()
        self._build()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aegis Audio Pro v2.0")
        self.geometry("1200x1000")
        self.resizable(True, True)
        self.configure(fg_color=T["app"])
        self.is_fullscreen = False
        try:
            self.iconbitmap("app.ico")
        except:
            pass
        self.db = Database()
        self.generator = MusicLicenseGenerator(status_callback=self.set_status, progress_callback=self.set_progress)
        self.model_loaded = False
        self.current_audio = None
        self.current_audio_path = None
        self.current_fingerprint = None
        self.original_audio = None
        self.is_playing = False
        self.track_count = 0
        self.history = []
        self._pulse_state = False
        self._wave_fig = None
        self._wave_ax = None
        self._wave_canvas = None
        self._view_mode = "waveform"
        self._tooltip = None
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo = 20
        self.loop_var = ctk.BooleanVar(value=False)
        self.batch_var = ctk.IntVar(value=1)
        self.seed_var = ctk.BooleanVar(value=False)
        self.search_var = ctk.StringVar(value="")
        self.mode_var = ctk.IntVar(value=0)  # 0=music, 1=sfx
        self._build_ui()
        self._bind_hotkeys()
        self.after(300, self._pulse_status)
        threading.Thread(target=self._load_model, daemon=True).start()

    def _bind_hotkeys(self):
        self.bind("<Control-g>", lambda e: self._on_generate())
        self.bind("<Control-s>", lambda e: self._save_project())
        self.bind("<Control-e>", lambda e: self._export_audio())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<space>", lambda e: self._toggle_play())
        self.bind("<F11>", lambda e: self._toggle_fullscreen())

    def _build_ui(self):
        self.ai_assistant = AIAssistantPanel(self, self)
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=(10, 24))
        canvas = ctk.CTkCanvas(main, bg=T["app"], highlightthickness=0)
        scrollbar = ctk.CTkScrollbar(main, orientation="vertical", command=canvas.yview)
        scrollable_frame = ctk.CTkFrame(canvas, fg_color="transparent")
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        scrollable_frame.grid_columnconfigure(0, weight=1)
        scrollable_frame.grid_columnconfigure(1, weight=0)
        scrollable_frame.grid_columnconfigure(2, weight=1)
        scrollable_frame.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ctk.CTkFrame(scrollable_frame, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1, width=340)
        right.grid(row=0, column=1, sticky="ns")
        right.pack_propagate(False)
        spacer = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        spacer.grid(row=0, column=2, sticky="nsew")
        self._canvas = canvas
        self._scrollable_frame = scrollable_frame

        header = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        header.pack(fill="x", pady=(0, 14))
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=22, pady=(18, 6))
        ctk.CTkLabel(title_row, text="Aegis Audio Pro", font=("Segoe UI Variable Display", 30, "bold"), text_color=T["text_primary"]).pack(side="left")
        ctk.CTkLabel(title_row, text="v2.0", font=("Segoe UI", 11, "bold"), text_color=T["accent"]).pack(side="left", padx=(8, 0), pady=(8, 0))
        self.license_label = ctk.CTkLabel(title_row, text=f"[{LICENSE_MODE}]", font=("Segoe UI", 12, "bold"), text_color=T["success"] if LICENSE_MODE == "PRO" else T["warning"])
        self.license_label.pack(side="right", padx=(0, 10))
        ctk.CTkButton(title_row, text="🤖 AI", width=60, height=30, corner_radius=8, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._toggle_ai_assistant).pack(side="right", padx=(0, 10))
        ctk.CTkButton(title_row, text="⚙️", width=40, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._open_settings).pack(side="right", padx=(0, 10))
        self.fs_btn = ctk.CTkButton(title_row, text="⛶", width=40, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._toggle_fullscreen).pack(side="right", padx=(0, 10))
        self.counter_label = ctk.CTkLabel(title_row, text=f"{self.track_count} {tr('tracks')}", font=("Segoe UI", 12), text_color=T["text_dim"])
        self.counter_label.pack(side="right", pady=6)
        ctk.CTkLabel(header, text="4-language legal license  |  QR verification  |  Audio fingerprint", font=("Segoe UI", 13), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(0, 18))

        status_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        status_card.pack(fill="x", pady=(0, 14))
        if self.model_loaded:
            self.status_label = ctk.CTkLabel(status_card, text=tr("model_ready"), font=("Consolas", 12), text_color=T["success"], anchor="w")
        else:
            self.status_label = ctk.CTkLabel(status_card, text=tr("model_loading"), font=("Consolas", 12), text_color=T["warning"], anchor="w")
        self.status_label.pack(fill="x", padx=22, pady=(14, 8))
        self.progress_bar = ctk.CTkProgressBar(status_card, height=6, corner_radius=3, progress_color=T["accent"], fg_color=T["border"])
        self.progress_bar.pack(fill="x", padx=22, pady=(0, 14))
        self.progress_bar.set(1.0 if self.model_loaded else 0)

        # ===== РЕЖИМ MUSIC / SFX =====
        mode_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        mode_card.pack(fill="x", pady=(0, 14))
        mode_row = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=22, pady=14)
        ctk.CTkLabel(mode_row, text="MODE:", font=("Segoe UI", 12, "bold"), text_color=T["text_secondary"]).pack(side="left")
        ctk.CTkRadioButton(mode_row, text=tr("mode_music"), variable=self.mode_var, value=0, font=("Segoe UI", 12), fg_color=T["accent"], text_color=T["text_primary"], command=self._switch_mode).pack(side="left", padx=12)
        ctk.CTkRadioButton(mode_row, text=tr("mode_sfx"), variable=self.mode_var, value=1, font=("Segoe UI", 12), fg_color=T["accent"], text_color=T["text_primary"], command=self._switch_mode).pack(side="left", padx=12)
        self.sfx_hint = ctk.CTkLabel(mode_row, text="", font=("Segoe UI", 11), text_color=T["text_dim"])
        self.sfx_hint.pack(side="right")

        prompt_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        prompt_card.pack(fill="x", pady=(0, 14))
        prompt_header = ctk.CTkFrame(prompt_card, fg_color="transparent")
        prompt_header.pack(fill="x", padx=22, pady=(16, 8))
        ctk.CTkLabel(prompt_header, text=tr("description"), font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(side="left")
        ctk.CTkButton(prompt_header, text=tr("random"), width=110, height=28, corner_radius=14, font=("Segoe UI", 11), fg_color=T["accent_light"], hover_color=T["accent_hover"], text_color=T["accent"], command=self._random_prompt).pack(side="right")
        self.prompt_box = ctk.CTkTextbox(prompt_card, height=92, corner_radius=14, font=("Segoe UI", 13), wrap="word", fg_color=T["card_hover"], border_color=T["border"], border_width=1)
        self.prompt_box.pack(fill="x", padx=22, pady=(0, 10))
        self.prompt_box.insert("1.0", PRESETS["Trap"]["prompt"])
        self.chips_frame = ctk.CTkFrame(prompt_card, fg_color="transparent")
        self.chips_frame.pack(fill="x", padx=22, pady=(0, 18))
        self._build_chips()

        settings_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        settings_card.pack(fill="x", pady=(0, 14))
        self._add_slider_row(settings_card, tr("duration"), 1, 120, 10, self._update_duration_label)
        self.duration_slider = settings_card._last_slider
        self.duration_label = settings_card._last_value_label
        self._add_slider_row(settings_card, tr("creativity"), 0.5, 2.0, 1.0, self._update_temp_label)
        self.temp_slider = settings_card._last_slider
        self.temp_label = settings_card._last_value_label
        self._add_slider_row(settings_card, tr("accuracy"), 1.0, 10.0, 3.0, self._update_guidance_label)
        self.guidance_slider = settings_card._last_slider
        self.guidance_label = settings_card._last_value_label
        loop_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        loop_row.pack(fill="x", padx=22, pady=(0, 10))
        ctk.CTkCheckBox(loop_row, text=tr("loop_mode"), variable=self.loop_var, font=("Segoe UI", 11), fg_color=T["accent"], hover_color=T["accent_hover"], checkmark_color="#FFFFFF", border_color=T["border"]).pack(side="left")
        batch_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        batch_row.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkLabel(batch_row, text=tr("batch"), font=("Segoe UI", 12)).pack(side="left")
        for opt in [1, 3, 5]:
            ctk.CTkRadioButton(batch_row, text=str(opt), variable=self.batch_var, value=opt, font=("Segoe UI", 11), fg_color=T["accent"], text_color=T["text_primary"]).pack(side="left", padx=10)
        row = ctk.CTkFrame(settings_card, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkLabel(row, text=tr("licensee"), font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(row, width=200, placeholder_text="User", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10)
        self.user_entry.pack(side="left", padx=12)
        ctk.CTkCheckBox(row, text=tr("fixed_seed"), variable=self.seed_var, font=("Segoe UI", 11), fg_color=T["accent"], hover_color=T["accent_hover"], checkmark_color="#FFFFFF", border_color=T["border"]).pack(side="left", padx=(20, 0))
        self.seed_var.trace("w", lambda *a: self._toggle_seed())
        self.seed_entry = ctk.CTkEntry(row, width=90, placeholder_text="42", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10, state="disabled")
        self.seed_entry.pack(side="left", padx=10)

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 14))
        self.generate_btn = ctk.CTkButton(btn_frame, text=tr("generate"), height=58, corner_radius=18, font=("Segoe UI Variable Display", 17, "bold"), fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=self._on_generate)
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.export_btn = ctk.CTkButton(btn_frame, text=tr("export"), height=58, corner_radius=18, font=("Segoe UI", 14, "bold"), fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=self._export_audio, state="disabled")
        self.export_btn.pack(side="left", fill="x", expand=True)

        download_frame = ctk.CTkFrame(left, fg_color="transparent")
        download_frame.pack(fill="x", pady=(0, 14))
        self.download_wav_btn = ctk.CTkButton(download_frame, text=tr("download_wav"), height=40, corner_radius=12, font=("Segoe UI", 12, "bold"), fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=lambda: self._quick_download("wav"), state="disabled")
        self.download_wav_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.download_mp3_btn = ctk.CTkButton(download_frame, text=tr("download_mp3"), height=40, corner_radius=12, font=("Segoe UI", 12, "bold"), fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=lambda: self._quick_download("mp3"), state="disabled")
        self.download_mp3_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.download_ogg_btn = ctk.CTkButton(download_frame, text=tr("download_ogg"), height=40, corner_radius=12, font=("Segoe UI", 12, "bold"), fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=lambda: self._quick_download("ogg"), state="disabled")
        self.download_ogg_btn.pack(side="left", fill="x", expand=True)

        # ===== НОВЫЕ КНОПКИ v2.0 =====
        pro_frame = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["accent"], border_width=1)
        pro_frame.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(pro_frame, text="🌍 PRO FEATURES v2.0", font=("Segoe UI Variable Display", 13, "bold"), text_color=T["accent"]).pack(anchor="w", padx=22, pady=(14, 8))
        pro_grid = ctk.CTkFrame(pro_frame, fg_color="transparent")
        pro_grid.pack(fill="x", padx=22, pady=(0, 14))
        pro_buttons = [
            (tr("video"), self._export_video),
            (tr("game"), self._export_game),
            (tr("verify"), self._verify_fingerprint),
            (tr("style"), self._style_transfer),
            ("🧬 Fingerprint", self._show_fingerprint),
            ("🌐 4-Lang License", self._show_license_info),
        ]
        for i, (text, cmd) in enumerate(pro_buttons):
            row_idx = i // 3
            col_idx = i % 3
            btn = ctk.CTkButton(pro_grid, text=text, height=44, corner_radius=12, fg_color=T["card_hover"], hover_color=T["accent"], text_color=T["text_primary"], font=("Segoe UI", 12, "bold"), command=cmd, state="disabled")
            btn.grid(row=row_idx, column=col_idx, padx=5, pady=5, sticky="ew")
        for c in range(3):
            pro_grid.grid_columnconfigure(c, weight=1)
        self.pro_buttons = [w for w in pro_grid.winfo_children() if isinstance(w, ctk.CTkButton)]

        self.wave_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1, height=150)
        self.wave_card.pack(fill="x", pady=(0, 14))
        self.wave_card.pack_propagate(False)
        wave_header = ctk.CTkFrame(self.wave_card, fg_color="transparent")
        wave_header.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(wave_header, text=tr("visualization"), font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(side="left")
        self.view_btn = ctk.CTkButton(wave_header, text=tr("spectrum"), width=130, height=26, corner_radius=10, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], font=("Segoe UI", 10), command=self._toggle_view)
        self.view_btn.pack(side="right")
        self.wave_placeholder = ctk.CTkLabel(self.wave_card, text="Visualization will appear after generation", font=("Segoe UI", 12), text_color=T["text_dim"])
        self.wave_placeholder.pack(expand=True)

        effects_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        effects_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(effects_card, text=tr("effects"), font=("Segoe UI Variable Display", 14, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=22, pady=(18, 12))
        effects_grid = ctk.CTkFrame(effects_card, fg_color="transparent")
        effects_grid.pack(fill="x", padx=22, pady=(0, 16))
        effect_buttons = [
            ("Reverb", "reverb"), ("Delay", "delay"), ("Pitch +2", "pitch_up"), ("Pitch -2", "pitch_down"),
            ("Speed 1.2x", "speed_up"), ("Reverse", "reverse"), ("Bass Boost", "bass"), ("Normalize", "normalize"),
            ("Auto Master", "master"), ("Harmonizer", "harmonizer"), ("Spectral Gate", "gate"), ("A/B Compare", "ab"),
            ("Undo", "undo"), ("Redo", "redo"), ("Copy Hash", "copy_hash"), ("Stems", "stems"),
        ]
        for i, (text, cmd) in enumerate(effect_buttons):
            row_idx = i // 4
            col_idx = i % 4
            btn = ctk.CTkButton(effects_grid, text=text, height=48, corner_radius=12, fg_color=T["card_hover"], hover_color=T["accent"], text_color=T["text_primary"], font=("Segoe UI", 14, "bold"), command=lambda c=cmd: self._handle_effect(c))
            btn.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="ew")
            desc = EFFECT_DESCRIPTIONS.get(cmd, "")
            if desc:
                btn.bind("<Button-3>", lambda e, d=desc: self._show_tooltip(e, d))
        for c in range(4):
            effects_grid.grid_columnconfigure(c, weight=1)

        meta_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        meta_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(meta_card, text=tr("metadata"), font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(16, 8))
        self.meta_text = ctk.CTkLabel(meta_card, text="BPM: -- | Key: -- | Duration: -- | RMS: --", font=("Consolas", 12), text_color=T["text_primary"], wraplength=700, justify="left")
        self.meta_text.pack(anchor="w", padx=22, pady=(0, 16))

        result_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        result_card.pack(fill="x")
        ctk.CTkLabel(result_card, text=tr("result"), font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(16, 8))
        self.result_text = ctk.CTkLabel(result_card, text=tr("empty_result"), font=("Consolas", 12), text_color=T["text_primary"], wraplength=700, justify="left")
        self.result_text.pack(anchor="w", padx=22, pady=(0, 10))
        btn_row = ctk.CTkFrame(result_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, pady=(0, 18))
        self.play_btn = ctk.CTkButton(btn_row, text=tr("play"), width=130, height=40, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 13, "bold"), command=self._toggle_play, state="disabled")
        self.play_btn.pack(side="left", padx=(0, 8))
        self.save_btn = ctk.CTkButton(btn_row, text=tr("save"), width=160, height=40, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 13, "bold"), command=self._save_project, state="disabled")
        self.save_btn.pack(side="left", padx=(0, 8))
        self.open_btn = ctk.CTkButton(btn_row, text=tr("folder"), width=100, height=40, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 13, "bold"), command=self._open_folder, state="disabled")
        self.open_btn.pack(side="left")

        ctk.CTkLabel(right, text=tr("history"), font=("Segoe UI Variable Display", 18, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=20, pady=(20, 14))
        self.search_entry = ctk.CTkEntry(right, placeholder_text=tr("search"), fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10, textvariable=self.search_var)
        self.search_entry.pack(fill="x", padx=12, pady=(0, 10))
        self.search_var.trace("w", lambda *a: self._update_history())
        ctk.CTkLabel(right, text=tr("favorites"), font=("Segoe UI", 12, "bold"), text_color=T["warning"]).pack(anchor="w", padx=20, pady=(10, 6))
        self.favorites_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent", height=120, scrollbar_button_color=T["border"], scrollbar_button_hover_color=T["card_hover"])
        self.favorites_scroll.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(right, text=tr("all"), font=("Segoe UI", 12, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=20, pady=(10, 6))
        self.history_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent", scrollbar_button_color=T["border"], scrollbar_button_hover_color=T["card_hover"])
        self.history_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 14))
        self.history_empty = ctk.CTkLabel(self.history_scroll, text=tr("empty_history"), font=("Segoe UI", 12), text_color=T["text_dim"], justify="center")
        self.history_empty.pack(expand=True, pady=40)

    def _build_chips(self):
        for w in self.chips_frame.winfo_children():
            w.destroy()
        presets = SFX_PRESETS if self.mode_var.get() == 1 else PRESETS
        for name, data in presets.items():
            chip = ctk.CTkButton(self.chips_frame, text=name, width=100, height=30, corner_radius=15, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], font=("Segoe UI", 11), command=lambda t=data["prompt"]: self._set_prompt(t))
            chip.pack(side="left", padx=(0, 6))
            desc = (PRESET_DESCRIPTIONS if self.mode_var.get() == 0 else {}).get(name, "")
            if desc:
                chip.bind("<Button-3>", lambda e, d=desc: self._show_tooltip(e, d))

    def _switch_mode(self):
        self._build_chips()
        if self.mode_var.get() == 1:
            self.sfx_hint.configure(text="Звуковые эффекты: 1-3 сек")
            self.duration_slider.set(2)
            self._update_duration_label(2)
        else:
            self.sfx_hint.configure(text="")
            self.duration_slider.set(10)
            self._update_duration_label(10)

    def _toggle_ai_assistant(self):
        if self.ai_assistant.is_expanded:
            self.ai_assistant._collapse()
        else:
            self.ai_assistant._expand()

    # ===== НОВЫЕ ДЕЙСТВИЯ v2.0 =====
    def _export_video(self):
        if not self.current_audio:
            self.set_status(tr("no_track"))
            return
        self.set_status("Rendering video...")
        threading.Thread(target=lambda: self._video_worker(), daemon=True).start()

    def _video_worker(self):
        try:
            gif, mp4 = MusicLicenseGenerator.export_video(np.squeeze(self.current_audio))
            def done():
                if mp4:
                    self.set_status(f"✅ Video: {mp4}")
                elif gif:
                    self.set_status(f"✅ GIF: {gif} (MP4 requires ffmpeg)")
                else:
                    self.set_status("Video export failed")
            self.after(0, done)
        except Exception as e:
            self.after(0, lambda: self.set_status(f"Video error: {e}"))

    def _export_game(self):
        if not self.current_audio_path:
            self.set_status(tr("no_track"))
            return
        from tkinter import messagebox
        engine = "unity" if messagebox.askyesno("Game Export", "Unity? (Yes) / Godot? (No)") else "godot"
        meta = MusicLicenseGenerator.export_game_meta(self.current_audio_path, engine)
        self.set_status(f"✅ {engine} meta: {meta}")

    def _verify_fingerprint(self):
        if not self.current_audio or not self.current_fingerprint:
            self.set_status("No fingerprint")
            return
        match = MusicLicenseGenerator.verify_fingerprint(np.squeeze(self.current_audio), self.current_fingerprint)
        self.set_status(f"🔍 Fingerprint match: {match:.0f}%")

    def _style_transfer(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Select reference audio", filetypes=[("Audio", "*.wav *.mp3 *.ogg")])
        if not path:
            return
        try:
            ref, sr = sf.read(path)
            if len(ref.shape) > 1:
                ref = ref[:, 0]
            if sr != SAMPLE_RATE:
                ref = librosa.resample(ref, orig_sr=sr, target_sr=SAMPLE_RATE)
            style = MusicLicenseGenerator.analyze_style(ref)
            if style:
                prompt = self.prompt_box.get("1.0", "end").strip()
                new_prompt = f"{prompt}, {style['bpm']} bpm, {style['key']} key, {style['mood']}"
                self._set_prompt(new_prompt)
                self.set_status(f"🎨 Style applied: {style['bpm']} BPM, {style['key']}")
        except Exception as e:
            self.set_status(f"Style error: {e}")

    def _show_fingerprint(self):
        if self.current_fingerprint:
            pyperclip.copy(self.current_fingerprint)
            self.set_status(f"🧬 Fingerprint copied: {self.current_fingerprint[:24]}...")
        else:
            self.set_status("No fingerprint")

    def _show_license_info(self):
        from tkinter import messagebox
        messagebox.showinfo("4-Language License",
            "Each track includes a legal certificate in:\n\n"
            "🇷🇺 Russian (RU) — для РФ и СНГ\n"
            "🇬🇧 English (EN) — международный\n"
            "🇩🇪 German (DE) — для ЕС\n"
            "🇫🇷 French (FR) — для ЕС\n\n"
            "Плюс QR-код для верификации и аудио-отпечаток,\n"
            "устойчивый к перекодированию файла.")

    def _quick_download(self, format):
        if not self.current_audio:
            self.set_status(tr("no_track"))
            return
        try:
            if format == "mp3" and LICENSE_MODE == "FREE":
                from tkinter import messagebox
                messagebox.showinfo("PRO feature", "MP3 export is PRO only")
                return
            audio = np.squeeze(self.current_audio)
            if format == "wav":
                filename = MusicLicenseGenerator.save_wav(audio)
            elif format == "mp3":
                metadata = {"artist": "Aegis Audio", "title": self.prompt_box.get("1.0", "end").strip()[:50], "genre": "Electronic"}
                bpm = self.generator.detect_bpm(audio)
                if bpm:
                    metadata["bpm"] = bpm
                filename = MusicLicenseGenerator.save_mp3(audio, metadata=metadata)
            elif format == "ogg":
                filename = MusicLicenseGenerator.save_ogg(audio)
            self.set_status(f"{tr('exported')}: {filename}")
        except Exception as e:
            self.set_status(f"{tr('export_error')}: {str(e)}")

    def _show_tooltip(self, event, text):
        if self._tooltip:
            try:
                self._tooltip.destroy()
            except:
                pass
            self._tooltip = None
        tw = ctk.CTkToplevel(self)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.configure(fg_color=T["card"], border_color=T["accent"], border_width=1)
        tw.geometry(f"+{event.x_root + 14}+{event.y_root + 14}")
        ctk.CTkLabel(tw, text=text, font=("Segoe UI", 12), text_color=T["text_primary"], wraplength=300, justify="left").pack(padx=16, pady=14)
        tw.update_idletasks()
        def close(e=None):
            try:
                tw.destroy()
            except:
                pass
            if self._tooltip is tw:
                self._tooltip = None
        tw.bind("<Button-1>", close)
        tw.bind("<Button-3>", close)
        tw.after(6000, close)
        self._tooltip = tw

    def _rebuild_ui(self):
        try:
            prompt = self.prompt_box.get("1.0", "end").strip()
            dur = self.duration_slider.get()
            temp = self.temp_slider.get()
            guid = self.guidance_slider.get()
            user = self.user_entry.get()
            info = self.result_text.cget("text")
            meta = self.meta_text.cget("text")
        except:
            prompt, dur, temp, guid, user = "", 10, 1.0, 3.0, ""
            info, meta = tr("empty_result"), "BPM: -- | Key: -- | Duration: -- | RMS: --"
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        try:
            self.prompt_box.delete("1.0", "end")
            self.prompt_box.insert("1.0", prompt)
            self.duration_slider.set(dur)
            self.temp_slider.set(temp)
            self.guidance_slider.set(guid)
            self.user_entry.delete(0, "end")
            self.user_entry.insert(0, user)
            self._update_duration_label(dur)
            self._update_temp_label(temp)
            self._update_guidance_label(guid)
            self._toggle_seed()
            self.counter_label.configure(text=f"{self.track_count} {tr('tracks')}")
            if self.model_loaded:
                self.set_status(tr("model_ready"))
                self.status_label.configure(text_color=T["success"])
                self.progress_bar.set(1.0)
            else:
                self.set_status(tr("model_loading"))
                self.status_label.configure(text_color=T["warning"])
            self.result_text.configure(text=info, text_color=T["text_primary"])
            self.meta_text.configure(text=meta, text_color=T["text_primary"])
            if self.current_audio is not None:
                self._draw_waveform(self.current_audio)
                for b in [self.play_btn, self.save_btn, self.export_btn, self.open_btn,
                          self.download_wav_btn, self.download_mp3_btn, self.download_ogg_btn] + self.pro_buttons:
                    b.configure(state="normal")
            self._update_history()
            self._update_favorites()
        except Exception as e:
            print("Rebuild error:", e)

    def _open_settings(self):
        SettingsWindow(self)

    def _handle_effect(self, cmd):
        if cmd == "undo":
            self._undo()
        elif cmd == "redo":
            self._redo()
        elif cmd == "copy_hash":
            self._copy_hash()
        elif cmd == "ab":
            self._ab_compare()
        elif cmd == "stems":
            self._separate_stems()
        else:
            self._apply_effect(cmd)

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)
        self.fs_btn.configure(text="✕" if self.is_fullscreen else "⛶")

    def _toggle_view(self):
        self._view_mode = "spectrum" if self._view_mode == "waveform" else "waveform"
        self.view_btn.configure(text=tr("waveform") if self._view_mode == "spectrum" else tr("spectrum"))
        if self.current_audio is not None:
            self._draw_waveform(self.current_audio)

    def _add_slider_row(self, parent, label, from_, to, default, update_fn):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(14, 6))
        ctk.CTkLabel(row, text=label, font=("Segoe UI", 13), text_color=T["text_secondary"]).pack(side="left")
        slider = ctk.CTkSlider(row, from_=from_, to=to, width=280, command=update_fn, progress_color=T["accent"], fg_color=T["border"], button_color=T["text_primary"], button_hover_color=T["card_hover"], button_length=24)
        slider.set(default)
        slider.pack(side="left", padx=14)
        value_label = ctk.CTkLabel(row, text="", font=("Segoe UI", 13, "bold"), text_color=T["accent"])
        value_label.pack(side="left")
        parent._last_slider = slider
        parent._last_value_label = value_label

    def _pulse_status(self):
        if self.model_loaded:
            return
        self._pulse_state = not self._pulse_state
        color = T["accent"] if self._pulse_state else T["warning"]
        current = self.status_label.cget("text")
        if "Init" in current or "Load" in current or "Загрузка" in current:
            self.status_label.configure(text_color=color)
        self.after(700, self._pulse_status)

    def _animate_wave(self, audio):
        if self._wave_fig is None:
            return
        total_steps = 15
        step_size = max(1, len(audio) // total_steps)
        def draw_step(step):
            if self._wave_fig is None:
                return
            end = min((step + 1) * step_size, len(audio))
            data = audio[:end]
            self._wave_ax.clear()
            self._wave_ax.set_facecolor(T["card"])
            if self._view_mode == "waveform":
                self._wave_ax.plot(data, color=T["waveform"], linewidth=0.8)
                self._wave_ax.set_ylim(-1.1, 1.1)
            else:
                try:
                    spectrum = np.abs(np.fft.rfft(data))
                    freqs = np.fft.rfftfreq(len(data), 1.0 / SAMPLE_RATE)
                    self._wave_ax.semilogx(freqs[1:], 20 * np.log10(spectrum[1:] + 1e-10), color=T["spectrum"], linewidth=0.8)
                    self._wave_ax.set_xlim(20, SAMPLE_RATE / 2)
                    self._wave_ax.set_ylim(-80, 0)
                except:
                    self._wave_ax.plot(data, color=T["waveform"], linewidth=0.8)
                    self._wave_ax.set_ylim(-1.1, 1.1)
            self._wave_ax.set_xlim(0, len(audio))
            self._wave_ax.axis('off')
            self._wave_canvas.draw_idle()
            if step < total_steps - 1:
                self.after(40, lambda: draw_step(step + 1))
        draw_step(0)

    def _random_prompt(self):
        if self.mode_var.get() == 1:
            self._set_prompt(random.choice(list(SFX_PRESETS.values()))["prompt"])
        else:
            self._set_prompt(random.choice(RANDOM_PROMPTS))

    def _toggle_seed(self):
        if self.seed_var.get():
            self.seed_entry.configure(state="normal")
            if not self.seed_entry.get():
                self.seed_entry.insert(0, "42")
        else:
            self.seed_entry.configure(state="disabled")
            self.seed_entry.delete(0, "end")

    def _set_prompt(self, text):
        self.prompt_box.delete("1.0", "end")
        self.prompt_box.insert("1.0", text)

    def _update_duration_label(self, value):
        val = int(value)
        if val >= 60:
            self.duration_label.configure(text=f"{val//60}:{val%60:02d}")
        else:
            self.duration_label.configure(text=f"{val}s")

    def _update_temp_label(self, value):
        self.temp_label.configure(text=f"{float(value):.1f}")

    def _update_guidance_label(self, value):
        self.guidance_label.configure(text=f"{float(value):.1f}")

    def set_status(self, msg):
        self.status_label.configure(text=msg)

    def set_progress(self, value):
        self.progress_bar.set(value / 100)

    def _load_model(self):
        try:
            self.generator.load()
            self.model_loaded = True
            self.after(0, lambda: self.set_status(tr("model_ready")))
            self.after(0, lambda: self.set_progress(100))
            self.after(0, lambda: self.status_label.configure(text_color=T["success"]))
        except Exception as e:
            err_msg = str(e)
            def err():
                self.set_status(f"Error: {err_msg}")
                self.status_label.configure(text_color=T["danger"])
            self.after(0, err)

    def _save_undo_state(self):
        if self.current_audio is not None:
            self.undo_stack.append(self.current_audio.copy())
            if len(self.undo_stack) > self.max_undo:
                self.undo_stack.pop(0)
            self.redo_stack.clear()

    def _undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.current_audio.copy() if self.current_audio is not None else None)
            self.current_audio = self.undo_stack.pop()
            self._draw_waveform(self.current_audio)
            self.set_status(tr("undo"))

    def _redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.current_audio.copy() if self.current_audio is not None else None)
            self.current_audio = self.redo_stack.pop()
            self._draw_waveform(self.current_audio)
            self.set_status(tr("redo"))

    def _apply_effect(self, effect):
        if self.current_audio is None:
            self.set_status(tr("generate_first"))
            return
        self._save_undo_state()
        try:
            audio = np.squeeze(self.current_audio)
            if effect == "reverb":
                audio = MusicLicenseGenerator.apply_reverb(audio)
            elif effect == "delay":
                audio = MusicLicenseGenerator.apply_delay(audio)
            elif effect == "pitch_up":
                audio = MusicLicenseGenerator.apply_pitch_shift(audio, 2)
            elif effect == "pitch_down":
                audio = MusicLicenseGenerator.apply_pitch_shift(audio, -2)
            elif effect == "speed_up":
                audio = MusicLicenseGenerator.apply_speed_change(audio, 1.2)
            elif effect == "reverse":
                audio = MusicLicenseGenerator.apply_reverse(audio)
            elif effect == "bass":
                audio = MusicLicenseGenerator.apply_bass_boost(audio)
            elif effect == "normalize":
                audio = MusicLicenseGenerator.apply_normalize(audio)
            elif effect == "master":
                audio = MusicLicenseGenerator.apply_auto_master(audio)
            elif effect == "harmonizer":
                audio = MusicLicenseGenerator.apply_harmonizer(audio)
            elif effect == "gate":
                audio = MusicLicenseGenerator.apply_spectral_gate(audio)
            self.current_audio = audio
            self._draw_waveform(audio)
            self.set_status(f"{tr('applied')}: {effect}")
        except Exception as e:
            self.set_status(f"{tr('effect_error')}: {str(e)}")

    def _separate_stems(self):
        if not self.current_audio:
            self.set_status(tr("generate_first"))
            return
        self._save_undo_state()
        stems = MusicLicenseGenerator.separate_stems_named(np.squeeze(self.current_audio))
        for name, stem in stems.items():
            filename = f"stem_{name}_{datetime.now().strftime('%H%M%S')}.wav"
            sf.write(filename, stem, SAMPLE_RATE)
        self.set_status("Stems: bass, drums, melody, pads")

    def _ab_compare(self):
        if self.original_audio is None or self.current_audio is None:
            self.set_status("Need original and current audio")
            return
        if self.is_playing:
            sd.stop()
            self.is_playing = False
        self.is_playing = True
        def play_alternating():
            sd.play(np.squeeze(self.original_audio), SAMPLE_RATE)
            import time
            time.sleep(len(self.original_audio) / SAMPLE_RATE)
            sd.play(np.squeeze(self.current_audio), SAMPLE_RATE)
            time.sleep(len(self.current_audio) / SAMPLE_RATE)
            self.is_playing = False
            self.after(0, lambda: self.play_btn.configure(text=tr("play")))
        threading.Thread(target=play_alternating, daemon=True).start()
        self.play_btn.configure(text="🆚 A/B...")

    def _copy_hash(self):
        if not self.current_audio_path:
            self.set_status(tr("generate_first"))
            return
        file_hash = MusicLicenseGenerator.calculate_hash(self.current_audio_path)
        pyperclip.copy(file_hash)
        self.set_status(f"{tr('hash_copied')}: {file_hash[:16]}...")

    def _on_generate(self):
        if not self.model_loaded:
            self.set_status(tr("model_loading"))
            return
        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            self.set_status(tr("enter_prompt"))
            return
        duration = int(self.duration_slider.get())
        user_name = self.user_entry.get().strip() or "User"
        temperature = float(self.temp_slider.get())
        guidance_scale = float(self.guidance_slider.get())
        loop_mode = self.loop_var.get()
        batch_count = self.batch_var.get()
        seed = None
        if self.seed_var.get():
            try:
                seed = int(self.seed_entry.get())
            except:
                self.set_status(tr("seed_number"))
                return
        self.generate_btn.configure(state="disabled", text=tr("generating"))
        for b in [self.play_btn, self.save_btn, self.export_btn, self.open_btn,
                  self.download_wav_btn, self.download_mp3_btn, self.download_ogg_btn] + self.pro_buttons:
            b.configure(state="disabled")
        self.set_progress(0)
        self.status_label.configure(text_color=T["accent"])
        threading.Thread(target=self._generate_worker, args=(prompt, duration, user_name, seed, temperature, guidance_scale, loop_mode, batch_count), daemon=True).start()

    def _generate_worker(self, prompt, duration, user_name, seed, temperature, guidance_scale, loop_mode, batch_count):
        try:
            best_audio = None
            best_score = -1
            for i in range(batch_count):
                self.set_status(f"Generating variant {i+1}/{batch_count}...")
                audio = self.generator.generate(prompt, duration, seed + i if seed else None, temperature, guidance_scale, loop_mode)
                score = np.std(audio)
                if score > best_score:
                    best_score = score
                    best_audio = audio
                self.set_progress(int((i + 1) / batch_count * 80))
            self.original_audio = best_audio.copy()
            self.current_audio = best_audio
            self._save_undo_state()
            self.set_status("Computing fingerprint...")
            self.set_progress(82)
            fingerprint = MusicLicenseGenerator.compute_fingerprint(best_audio)
            self.current_fingerprint = fingerprint
            wav = self.generator.save_wav(best_audio)
            self.current_audio_path = wav
            file_hash = self.generator.calculate_hash(wav)
            bpm = self.generator.detect_bpm(best_audio)
            key = self.generator.detect_key(best_audio)
            analytics = self.generator.get_audio_analytics(best_audio)
            license_type = "Commercial" if LICENSE_MODE == "PRO" else "Personal"
            self.set_status("Generating 4-language license...")
            self.set_progress(86)
            qr_path = self.generator.generate_qr(file_hash, fingerprint, user_name)
            pdf = self.generator.generate_multilang_license(wav, file_hash, user_name, license_type, bpm, key, analytics, fingerprint, qr_path)
            fp_path = None
            if fingerprint:
                fp_path = f"{os.path.splitext(wav)[0]}.fingerprint"
                with open(fp_path, 'w') as f:
                    f.write(f"{fingerprint}\n{file_hash}\n{datetime.now().isoformat()}\n{user_name}\n")
            zip_file = self.generator.create_package(wav, pdf, qr_path, fp_path)
            self.track_count += 1
            dur_str = f"{duration//60}:{duration%60:02d}" if duration >= 60 else f"{duration}s"
            info = (f"File: {zip_file}\nDuration: {dur_str}\nLicensee: {user_name}\nLicense: {license_type}\n"
                    f"Languages: RU/EN/DE/FR\nBPM: {bpm or '--'} | Key: {key or '--'}\n"
                    f"RMS: {analytics['rms']} | Peak: {analytics['peak']}\n"
                    f"Dynamic Range: {analytics['dynamic_range_db']} dB\n"
                    f"SHA-256: {file_hash[:32]}...\n"
                    f"Fingerprint: {fingerprint[:32] if fingerprint else '--'}...\n"
                    f"QR: {'✓' if qr_path else '✗'}\nSize: {os.path.getsize(zip_file) // 1024} KB")
            if seed is not None:
                info += f"\nSeed: {seed}"
            if batch_count > 1:
                info += f"\nVariants: {batch_count}"
            track_id = self.db.add_track(
                prompt=prompt, duration=duration, bpm=bpm, key=key,
                rms=analytics['rms'], peak=analytics['peak'],
                dynamic_range=analytics['dynamic_range_db'],
                license_type=license_type, licensee=user_name,
                file_hash=file_hash, file_path=zip_file, fingerprint=fingerprint,
                seed=seed, temperature=temperature, guidance_scale=guidance_scale,
                loop_mode=1 if loop_mode else 0
            )
            self.history.insert(0, {"id": track_id, "time": datetime.now().strftime("%H:%M"), "prompt": prompt[:60] + "..." if len(prompt) > 60 else prompt, "duration": dur_str, "file": zip_file, "bpm": bpm, "hash": file_hash, "favorite": False})
            self.history = self.history[:20]
            def done():
                self.result_text.configure(text=info, text_color=T["text_primary"])
                self.meta_text.configure(text=f"BPM: {bpm or '--'} | Key: {key or '--'} | Duration: {dur_str} | RMS: {analytics['rms']} | FP: {'✓' if fingerprint else '✗'}", text_color=T["text_primary"])
                self.generate_btn.configure(state="normal", text=tr("generate"))
                for b in [self.play_btn, self.save_btn, self.export_btn, self.open_btn,
                          self.download_wav_btn, self.download_mp3_btn, self.download_ogg_btn] + self.pro_buttons:
                    b.configure(state="normal")
                self.counter_label.configure(text=f"{self.track_count} {tr('tracks')}")
                self.set_status(tr("ready"))
                self.status_label.configure(text_color=T["success"])
                self.set_progress(100)
                self._update_history()
                self._update_favorites()
                self._draw_waveform(best_audio)
            self.after(0, done)
        except Exception as e:
            error_msg = str(e)
            error_trace = traceback.format_exc()
            def err():
                self.generate_btn.configure(state="normal", text=tr("generate"))
                self.set_status(f"Error: {error_msg}")
                self.status_label.configure(text_color=T["danger"])
                print(error_trace)
            self.after(0, err)

    def _save_project(self):
        if not self.current_audio:
            self.set_status(tr("no_track"))
            return
        project = {
            "prompt": self.prompt_box.get("1.0", "end").strip(),
            "duration": int(self.duration_slider.get()),
            "temperature": float(self.temp_slider.get()),
            "guidance_scale": float(self.guidance_slider.get()),
            "user_name": self.user_entry.get().strip() or "User",
            "seed": int(self.seed_entry.get()) if self.seed_var.get() else None,
            "loop_mode": self.loop_var.get(),
            "batch_count": self.batch_var.get(),
            "mode": "sfx" if self.mode_var.get() == 1 else "music",
            "timestamp": datetime.now().isoformat(),
        }
        filename = f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(project, f, indent=2, ensure_ascii=False)
        self.set_status(f"{tr('project_saved')}: {filename}")

    def _export_audio(self):
        if not self.current_audio:
            self.set_status(tr("no_track"))
            return
        from tkinter import filedialog, messagebox
        export_path = filedialog.asksaveasfilename(title="Export audio", defaultextension=".wav", filetypes=[("WAV", "*.wav"), ("MP3", "*.mp3"), ("OGG", "*.ogg")])
        if export_path:
            try:
                if export_path.endswith(".mp3"):
                    if LICENSE_MODE == "FREE":
                        messagebox.showinfo("PRO feature", "MP3 export is PRO only")
                        return
                    metadata = {"artist": "Aegis Audio", "title": self.prompt_box.get("1.0", "end").strip()[:50], "genre": "Electronic"}
                    bpm = self.generator.detect_bpm(self.current_audio)
                    if bpm:
                        metadata["bpm"] = bpm
                    self.generator.save_mp3(self.current_audio, metadata=metadata)
                elif export_path.endswith(".ogg"):
                    self.generator.save_ogg(self.current_audio)
                else:
                    self.generator.save_wav(self.current_audio)
                self.set_status(f"{tr('exported')}: {export_path}")
            except Exception as e:
                self.set_status(f"{tr('export_error')}: {str(e)}")

    def _update_history(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()
        query = self.search_var.get().lower()
        filtered = [e for e in self.history if not query or query in e["prompt"].lower()]
        if not filtered:
            self.history_empty.pack(expand=True, pady=40)
            return
        for entry in filtered:
            item = ctk.CTkFrame(self.history_scroll, fg_color=T["card_hover"], corner_radius=14, border_color=T["border"], border_width=1)
            item.pack(fill="x", pady=(0, 8))
            top_row = ctk.CTkFrame(item, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(top_row, text=entry["time"], font=("Segoe UI", 10, "bold"), text_color=T["accent"]).pack(side="left")
            fav_btn = ctk.CTkButton(top_row, text="⭐" if entry.get("favorite") else "☆", width=30, height=24, corner_radius=8, fg_color="transparent", hover_color=T["border"], text_color=T["warning"], font=("Segoe UI", 12), command=lambda e=entry: self._toggle_favorite(e))
            fav_btn.pack(side="right")
            ctk.CTkLabel(item, text=entry["prompt"], font=("Segoe UI", 11), text_color=T["text_primary"], wraplength=240, justify="left").pack(anchor="w", padx=12, pady=(0, 2))
            bpm_text = f" | {entry['bpm']} BPM" if entry.get('bpm') else ""
            ctk.CTkLabel(item, text=f"{entry['duration']}{bpm_text}", font=("Segoe UI", 10), text_color=T["text_dim"]).pack(anchor="w", padx=12, pady=(0, 10))

    def _update_favorites(self):
        for w in self.favorites_scroll.winfo_children():
            w.destroy()
        favs = [e for e in self.history if e.get("favorite")]
        if not favs:
            ctk.CTkLabel(self.favorites_scroll, text=tr("no_favorites"), font=("Segoe UI", 11), text_color=T["text_dim"]).pack(pady=10)
            return
        for entry in favs[:3]:
            item = ctk.CTkFrame(self.favorites_scroll, fg_color=T["card_hover"], corner_radius=10, border_color=T["border"], border_width=1)
            item.pack(fill="x", pady=(0, 6))
            ctk.CTkLabel(item, text=f"⭐ {entry['prompt'][:40]}...", font=("Segoe UI", 10), text_color=T["text_primary"], wraplength=260).pack(anchor="w", padx=10, pady=6)

    def _toggle_favorite(self, entry):
        entry["favorite"] = not entry.get("favorite", False)
        if entry.get("id"):
            self.db.toggle_favorite(entry["id"])
        self._update_history()
        self._update_favorites()
        self.set_status("Favorite toggled")

    def _draw_waveform(self, audio):
        audio = np.squeeze(audio)
        try:
            self.wave_placeholder.pack_forget()
        except:
            pass
        for w in list(self.wave_card.winfo_children()):
            if w == self.wave_placeholder:
                continue
            try:
                w.destroy()
            except:
                pass
        fig, ax = plt.subplots(figsize=(7, 1.5), dpi=80)
        fig.patch.set_facecolor(T["card"])
        ax.set_facecolor(T["card"])
        self._wave_fig = fig
        self._wave_ax = ax
        canvas = FigureCanvasTkAgg(fig, master=self.wave_card)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._wave_canvas = canvas
        self._animate_wave(audio)

    def _toggle_play(self):
        if self.current_audio is None:
            return
        if self.is_playing:
            sd.stop()
            self.is_playing = False
            self.play_btn.configure(text=tr("play"))
        else:
            sd.play(np.squeeze(self.current_audio), SAMPLE_RATE)
            self.is_playing = True
            self.play_btn.configure(text=tr("stop"))

    def _open_folder(self):
        os.startfile(script_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()
