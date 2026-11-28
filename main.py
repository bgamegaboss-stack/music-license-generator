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

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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
        "danger": "#FF3B30", "island": "#000000", "island_text": "#FFFFFF",
        "waveform": "#00E5FF", "spectrum": "#FF6B35"
    },
    "light": {
        "app": "#F2F2F7", "card": "#FFFFFF", "card_hover": "#F9F9FB",
        "border": "#E5E5EA", "text_primary": "#1C1C1E", "text_secondary": "#3A3A3C",
        "text_dim": "#8E8E93", "accent": "#007AFF", "accent_hover": "#0066CC",
        "accent_light": "#E5F1FF", "success": "#34C759", "warning": "#FF9500",
        "danger": "#FF3B30", "island": "#1C1C1E", "island_text": "#FFFFFF",
        "waveform": "#007AFF", "spectrum": "#FF3B30"
    },
    "midnight": {
        "app": "#0A0A1F", "card": "#151530", "card_hover": "#1F1F45",
        "border": "#2A2A55", "text_primary": "#E0E0FF", "text_secondary": "#A0A0C0",
        "text_dim": "#606080", "accent": "#7C4DFF", "accent_hover": "#651FFF",
        "accent_light": "#EDE7F6", "success": "#00E676", "warning": "#FFAB40",
        "danger": "#FF5252", "island": "#0A0A1F", "island_text": "#E0E0FF",
        "waveform": "#7C4DFF", "spectrum": "#FF4081"
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

PROMO_CODES = {
    "BETA2026": "PRO",
    "INDIEDEV": "PRO",
    "AEGISLAUNCH": "PRO",
}

PRESETS = {
    "Synthwave": {"prompt": "dark synthwave chase scene, heavy bass, 120 bpm, retro analog synths", "bpm": 120, "key": "A minor"},
    "Cyberpunk": {"prompt": "cyberpunk industrial techno, distorted bass, glitchy percussion, 128 bpm", "bpm": 128, "key": "D minor"},
    "Epic Orchestral": {"prompt": "epic cinematic orchestral trailer music, brass, choir, timpani, 90 bpm", "bpm": 90, "key": "C minor"},
    "Lo-fi Chill": {"prompt": "lo-fi hip hop beat, warm vinyl crackle, mellow piano, chill, 80 bpm", "bpm": 80, "key": "F major"},
    "Trap": {"prompt": "aggressive drill trap instrumental, distorted 808 sub-bass sliding notes, rapid triplet hi-hats rolls, dark minor key melody, crisp snare hits, 140 bpm", "bpm": 140, "key": "G minor"},
    "Ambient": {"prompt": "ambient space drone, ethereal pads, slow evolving textures, 60 bpm", "bpm": 60, "key": "E minor"},
    "Dark Cinematic": {"prompt": "dark cinematic tension, low strings, ominous atmosphere, 70 bpm", "bpm": 70, "key": "B minor"},
    "Electronic": {"prompt": "upbeat electronic dance music, energetic synths, driving beat, 128 bpm", "bpm": 128, "key": "A major"},
}

EFFECT_DESCRIPTIONS = {
    "reverb": "Эхо/пространство. Эффект 'большого зала' — звук объёмнее и шире.",
    "delay": "Повтор. Звук повторяется с задержкой, как ритмичное эхо.",
    "pitch_up": "Выше на 2 полутона. Мелодия светлее и выше.",
    "pitch_down": "Ниже на 2 полутона. Мелодия темнее и ниже.",
    "speed_up": "Быстрее на 20%. Темп выше.",
    "reverse": "Задом наперёд. Проигрывает трек в обратную сторону.",
    "bass": "Усиление баса. Низкие частоты громче — звук 'жирнее'.",
    "normalize": "Выровнять громкость. Стандартная громкость.",
    "master": "Авто-мастеринг. Компрессор + лимитер + нормализация.",
    "harmonizer": "Гармонии. Добавляет октавы и квинты.",
    "gate": "Убрать шум. Глушит тихие участки.",
    "ab": "Сравнить. По очереди оригинал и обработанный.",
    "undo": "Отменить. Возврат к предыдущему состоянию.",
    "redo": "Вернуть. Повтор отменённого.",
    "copy_hash": "Копировать SHA-256 хеш файла.",
    "stems": "Разделить на бас/средние/высокие отдельными файлами.",
    "sidechain": "Сайдчейн. Приглушение под ритм — эффект 'дыхания'.",
    "vinyl": "Винил. Тёплый шум + wow/flutter — lo-fi атмосфера.",
    "game_export": "Game Ready. Пакет для Godot/Unity с .meta.",
}

PRESET_DESCRIPTIONS = {
    "Synthwave": "Ретро-электроника 80-х, как в киберпанк-гонках.",
    "Cyberpunk": "Жёсткий индастриал-техно с искажениями.",
    "Epic Orchestral": "Мощный оркестр для трейлеров и финальных битв.",
    "Lo-fi Chill": "Спокойный бит для фона и учёбы.",
    "Trap": "Агрессивный хип-хоп с глубоким басом 808.",
    "Ambient": "Медитативный космический эмбиент без ритма.",
    "Dark Cinematic": "Тревожная атмосфера для хоррора и напряжённых сцен.",
    "Electronic": "Энергичный танцевальный трек с драйвом.",
}

RU_COMMANDS = {
    "обрежь": "trim", "обрезать": "trim", "trim": "trim",
    "фейд ин": "fade in", "fade in": "fade in", "плавное начало": "fade in",
    "фейд аут": "fade out", "fade out": "fade out", "плавный конец": "fade out",
    "громче": "louder", "louder": "louder", "усиль": "louder",
    "луп": "loop", "loop": "loop", "зациклить": "loop", "цикл": "loop",
    "реверс": "reverse", "reverse": "reverse", "обратно": "reverse",
    "реверб": "reverb", "reverb": "reverb", "эхо": "reverb", "зал": "reverb",
    "дилей": "delay", "delay": "delay", "задержка": "delay",
    "бас": "bass", "bass": "bass", "низкие": "bass", "саб": "bass",
    "нормализ": "normalize", "normalize": "normalize", "выровнять": "normalize",
    "мастер": "master", "master": "master", "мастеринг": "master",
    "гармонии": "harmonizer", "harmonizer": "harmonizer",
    "гейт": "gate", "gate": "gate", "убрать шум": "gate",
    "сравнить": "ab", "ab": "ab",
    "отмена": "undo", "undo": "undo",
    "вернуть": "redo", "redo": "redo",
    "хеш": "copy_hash", "copy_hash": "copy_hash",
    "стемы": "stems", "stems": "stems", "разделить": "stems", "дорожки": "stems",
    "питч": "pitch", "pitch": "pitch", "высота": "pitch",
    "скорость": "speed", "speed": "speed", "быстрее": "speed_up",
    "стата": "stats", "stats": "stats", "статистика": "stats", "аналитика": "stats",
    "аккорды": "chords", "chords": "chords", "прогрессия": "chords",
    "экспорт": "export", "export": "export", "скачать": "export", "mp3": "export",
    "сайдчейн": "sidechain", "sidechain": "sidechain",
    "винил": "vinyl", "vinyl": "vinyl",
    "гейм": "game_export", "game_export": "game_export", "godot": "game_export", "unity": "game_export",
}

CHORD_PROGRESSIONS = [
    ("Pop", "I-V-vi-IV", "C G Am F"),
    ("Emotional", "vi-IV-I-V", "Am F C G"),
    ("Rock", "I-IV-V-IV", "C F G F"),
    ("Jazz", "ii-V-I", "Dm7 G7 Cmaj7"),
    ("Dark", "i-VI-III-VII", "Am F C G"),
    ("Epic", "i-III-VII-VI", "Am C G F"),
]

RANDOM_PROMPTS = [
    "mysterious underwater exploration theme, deep sub-bass, echoing sonar pings, ethereal pads",
    "high-speed racing game soundtrack, adrenaline-pumping electronic rock, distorted guitars, fast tempo",
    "medieval fantasy tavern music, lute, flute, cheerful folk melody, acoustic instruments",
    "horror game ambient, unsettling drones, distant whispers, creaking sounds, psychological tension",
]

LANG_UI = {
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
        "game_ready": "🎮 Game Ready (Godot/Unity)",
        "bpm_field": "BPM", "key_field": "Key",
        "promo_code": "Промокод", "apply_code": "Активировать",
        "code_active": "✅ PRO активен", "code_inactive": "⚠️ FREE режим",
        "code_success": "Промокод принят — PRO активирован!",
        "code_fail": "Неверный промокод",
        "license_lang": "Язык лицензии",
        "license_all": "Все 4 языка",
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
        "game_ready": "🎮 Game Ready (Godot/Unity)",
        "bpm_field": "BPM", "key_field": "Key",
        "promo_code": "Promo code", "apply_code": "Activate",
        "code_active": "✅ PRO active", "code_inactive": "⚠️ FREE mode",
        "code_success": "Promo code accepted — PRO activated!",
        "code_fail": "Invalid promo code",
        "license_lang": "License language",
        "license_all": "All 4 languages",
    }
}

def tr(key):
    return LANG_UI[CURRENT_LANG].get(key, key)


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
            file_path TEXT, favorite INTEGER DEFAULT 0, seed INTEGER,
            temperature REAL, guidance_scale REAL, loop_mode INTEGER DEFAULT 0,
            audio_preview TEXT)''')
        self.conn.commit()

    def add_track(self, **kw):
        self.cursor.execute('''INSERT INTO tracks (timestamp, prompt, duration, bpm, key, rms, peak,
            dynamic_range, license_type, licensee, file_hash, file_path, favorite,
            seed, temperature, guidance_scale, loop_mode, audio_preview)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            kw.get('timestamp', datetime.now().isoformat()), kw.get('prompt', ''),
            kw.get('duration', 0), kw.get('bpm'), kw.get('key'), kw.get('rms'),
            kw.get('peak'), kw.get('dynamic_range'), kw.get('license_type', 'Personal'),
            kw.get('licensee', 'User'), kw.get('file_hash', ''), kw.get('file_path', ''),
            kw.get('favorite', 0), kw.get('seed'), kw.get('temperature', 1.0),
            kw.get('guidance_scale', 3.0), kw.get('loop_mode', 0), kw.get('audio_preview', '')))
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
            self.status("Generating: melody start...")
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
                ctx_samples = CONTEXT_TAIL * SAMPLE_RATE
                if len(result) < ctx_samples:
                    ctx_samples = len(result)
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
            self.status("Loop mode applied")
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
    def save_flac(audio, samplerate=SAMPLE_RATE):
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
        audio_int16 = (audio * 32767).astype(np.int16)
        audio_segment = AudioSegment(audio_int16.tobytes(), frame_rate=samplerate, sample_width=audio_int16.dtype.itemsize, channels=1)
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.flac"
        audio_segment.export(filename, format="flac")
        return filename

    @staticmethod
    def save_midi(audio, samplerate=SAMPLE_RATE):
        try:
            pitches, magnitudes = librosa.piptrack(y=audio, sr=samplerate)
            midi_notes = []
            threshold = np.median(magnitudes) * 2
            for t in range(pitches.shape[1]):
                for f in range(pitches.shape[0]):
                    if magnitudes[f, t] > threshold and 50 < pitches[f, t] < 2000:
                        midi_note = librosa.hz_to_midi(pitches[f, t])
                        midi_notes.append((t * 512 / samplerate, int(round(midi_note)), 100))
                        break
            midi = pretty_midi.PrettyMIDI()
            piano = pretty_midi.Instrument(program=0)
            if midi_notes:
                midi_notes.sort(key=lambda x: x[0])
                for i, (time_sec, note, vel) in enumerate(midi_notes):
                    duration = 0.1
                    if i + 1 < len(midi_notes):
                        duration = min(0.5, midi_notes[i+1][0] - time_sec)
                    piano.notes.append(pretty_midi.Note(velocity=vel, pitch=note, start=time_sec, end=time_sec + duration))
            midi.instruments.append(piano)
            filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mid"
            midi.write(filename)
            return filename
        except Exception as e:
            print(f"MIDI export error: {e}")
            return None

    @staticmethod
    def calculate_hash(filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

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
            low_band = lfilter(b, a, result)
            gain = 10 ** (low_gain_db / 20)
            result = result + low_band * (gain - 1)
        if mid_gain_db != 0:
            b1, a1 = butter(2, 300 / nyq, btype='high')
            b2, a2 = butter(2, 3000 / nyq, btype='low')
            mid_band = lfilter(b2, a2, lfilter(b1, a1, result))
            gain = 10 ** (mid_gain_db / 20)
            result = result + mid_band * (gain - 1)
        if high_gain_db != 0:
            b, a = butter(2, 3000 / nyq, btype='high')
            high_band = lfilter(b, a, result)
            gain = 10 ** (high_gain_db / 20)
            result = result + high_band * (gain - 1)
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result = result / peak
        return result

    @staticmethod
    def apply_compressor(audio, threshold=-12, ratio=4.0, attack=0.01, release=0.1):
        threshold_lin = 10 ** (threshold / 20)
        attack_samples = int(attack * SAMPLE_RATE)
        release_samples = int(release * SAMPLE_RATE)
        envelope = np.abs(audio)
        envelope = uniform_filter1d(envelope, size=max(1, attack_samples))
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

    @staticmethod
    def apply_sidechain_ducking(audio, rate_hz=2.0, depth=0.6):
        result = audio.copy()
        period_samples = int(SAMPLE_RATE / rate_hz)
        duck_samples = int(period_samples * 0.4)
        for i in range(0, len(result), period_samples):
            end = min(i + duck_samples, len(result))
            duck_len = end - i
            if duck_len > 0:
                envelope = np.ones(duck_len)
                attack_len = min(int(duck_len * 0.2), duck_len)
                release_len = duck_len - attack_len
                if attack_len > 0:
                    envelope[:attack_len] = np.linspace(1.0, 1.0 - depth, attack_len)
                if release_len > 0:
                    envelope[attack_len:] = np.linspace(1.0 - depth, 1.0, release_len)
                result[i:end] *= envelope
        return result

    @staticmethod
    def apply_vinyl_effect(audio):
        result = audio.copy()
        b, a = butter(2, 12000 / (SAMPLE_RATE / 2), btype='low')
        result = lfilter(b, a, result)
        b2, a2 = butter(2, 8000 / (SAMPLE_RATE / 2), btype='low')
        result = lfilter(b2, a2, result)
        noise_len = len(result)
        white_noise = np.random.normal(0, 0.008, noise_len)
        pink_noise = lfilter([0.049922035, -0.095993829, 0.050612699, -0.004709510,
                              0.000000000, 0.000000000, 0.000000000],
                             [1.0, -1.494884428, 0.749598244, -0.093982110,
                              0.014253612, -0.013413925, 0.003291887],
                             white_noise)
        result = result + pink_noise * 0.3
        t = np.arange(noise_len) / SAMPLE_RATE
        wow = 1.0 + 0.002 * np.sin(2 * np.pi * 0.8 * t)
        flutter = 1.0 + 0.001 * np.sin(2 * np.pi * 6.0 * t)
        result = result * wow * flutter
        result = MusicLicenseGenerator.apply_compressor(result, threshold=-15, ratio=2.0)
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result = result / peak
        return result

    @staticmethod
    def separate_stems_simple(audio):
        nyq = SAMPLE_RATE / 2
        b_low, a_low = butter(2, 250 / nyq, btype='low')
        b_mid, a_mid = butter(2, [250 / nyq, 4000 / nyq], btype='band')
        b_high, a_high = butter(2, 4000 / nyq, btype='high')
        return {"bass": lfilter(b_low, a_low, audio), "mid": lfilter(b_mid, a_mid, audio), "high": lfilter(b_high, a_high, audio)}

    @staticmethod
    def _get_unicode_font():
        candidates = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/msyh.ttf",
            "C:/Windows/Fonts/arialuni.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _generate_qr_png(data):
        if not HAS_QRCODE:
            return None
        try:
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            filename = f"qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            img.save(filename)
            return filename
        except Exception as e:
            print(f"QR error: {e}")
            return None

    @staticmethod
    def generate_license_pdf(audio_filename, file_hash, user_name, license_type="Commercial",
                              bpm=None, key=None, analytics=None):
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        font_path = MusicLicenseGenerator._get_unicode_font()
        use_unicode = False
        if font_path:
            try:
                pdf.add_font("Uni", "", font_path)
                pdf.add_font("Uni", "B", font_path)
                use_unicode = True
            except:
                use_unicode = False

        def set_font(style="", size=11):
            if use_unicode:
                pdf.set_font("Uni", style, size)
            else:
                pdf.set_font("Arial", style, size)

        # Страница 1: EN + QR
        pdf.add_page()
        set_font("B", 22)
        pdf.cell(0, 14, txt="AEGIS AUDIO PRO", ln=True, align="C")
        set_font("", 12)
        pdf.cell(0, 8, txt="Royalty-Free AI Audio Licensing Platform", ln=True, align="C")
        pdf.ln(6)

        qr_data = f"AEGIS|SHA256:{file_hash}|FILE:{audio_filename}|LICENSED_TO:{user_name}"
        qr_path = MusicLicenseGenerator._generate_qr_png(qr_data)

        if qr_path and os.path.exists(qr_path):
            pdf.image(qr_path, x=15, y=pdf.get_y(), w=55)
            pdf.set_xy(75, pdf.get_y())
            set_font("B", 13)
            pdf.cell(0, 10, txt="COMMERCIAL LICENSE CERTIFICATE", ln=True)
            pdf.set_x(75)
            set_font("", 10)
            pdf.cell(0, 6, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
            pdf.set_x(75)
            pdf.cell(0, 6, txt=f"License Holder: {user_name}", ln=True)
            pdf.set_x(75)
            pdf.cell(0, 6, txt=f"Audio File: {audio_filename}", ln=True)
            pdf.set_x(75)
            if bpm:
                pdf.cell(0, 6, txt=f"BPM: {bpm}", ln=True)
                pdf.set_x(75)
            if key:
                pdf.cell(0, 6, txt=f"Key: {key}", ln=True)
                pdf.set_x(75)
            if analytics:
                pdf.cell(0, 6, txt=f"Duration: {analytics['duration']}s", ln=True)
                pdf.set_x(75)
            pdf.cell(0, 6, txt=f"License Type: {license_type}", ln=True)
            pdf.set_x(75)
            pdf.cell(0, 6, txt=f"SHA-256: {file_hash[:32]}...", ln=True)
            pdf.set_y(80)
        else:
            set_font("B", 13)
            pdf.cell(0, 10, txt="COMMERCIAL LICENSE CERTIFICATE", ln=True, align="C")
            set_font("", 10)
            pdf.cell(0, 6, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
            pdf.cell(0, 6, txt=f"License Holder: {user_name}", ln=True)
            pdf.cell(0, 6, txt=f"Audio File: {audio_filename}", ln=True)
            if bpm:
                pdf.cell(0, 6, txt=f"BPM: {bpm}", ln=True)
            if key:
                pdf.cell(0, 6, txt=f"Key: {key}", ln=True)
            if analytics:
                pdf.cell(0, 6, txt=f"Duration: {analytics['duration']}s", ln=True)
            pdf.cell(0, 6, txt=f"License Type: {license_type}", ln=True)
            pdf.cell(0, 6, txt=f"SHA-256: {file_hash[:32]}...", ln=True)

        pdf.ln(6)
        set_font("B", 12)
        pdf.cell(0, 10, txt="LICENSE TERMS", ln=True)
        pdf.ln(2)
        set_font("", 10)
        terms_en = (
            "This certificate grants the License Holder a perpetual, worldwide, "
            "non-exclusive, royalty-free license to use the specified audio file for any "
            "commercial purpose, including video games, films, advertisements, streaming "
            "content, and other media projects.\n\n"
            "The audio was generated using AI trained exclusively on open-source and "
            "public domain datasets. You are free to modify, distribute, and monetize this "
            "file without restrictions or attribution requirements.\n\n"
            "This license is tied to the specific file hash above and cannot be transferred.\n\n"
            "Scan the QR code to verify license authenticity."
        )
        pdf.multi_cell(0, 5, txt=terms_en)
        pdf.ln(4)
        set_font("B", 10)
        pdf.cell(0, 8, txt="Issued by: Aegis Audio Pro", ln=True)

        # Страница 2: DE
        pdf.add_page()
        set_font("B", 22)
        pdf.cell(0, 14, txt="AEGIS AUDIO PRO", ln=True, align="C")
        set_font("B", 13)
        pdf.cell(0, 10, txt="GEWERBELICHE LIZENZBESCHEINIGUNG", ln=True, align="C")
        set_font("", 10)
        pdf.cell(0, 6, txt=f"Lizenzdatum: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(0, 6, txt=f"Lizenzinhaber: {user_name}", ln=True)
        pdf.cell(0, 6, txt=f"Audiodatei: {audio_filename}", ln=True)
        pdf.cell(0, 6, txt=f"Datei-Hash: {file_hash[:32]}...", ln=True)
        pdf.ln(6)
        set_font("B", 12)
        pdf.cell(0, 10, txt="LIZENZBEDINGUNGEN", ln=True)
        pdf.ln(2)
        set_font("", 10)
        terms_de = (
            "Diese Bescheinigung gewährt dem Lizenzinhaber eine unbefristete, weltweite, "
            "nicht-exklusive, lizenzfreie Lizenz zur Nutzung der angegebenen Audiodatei "
            "für jeden kommerziellen Zweck, einschließlich Videospiele, Filme, Werbung "
            "und andere Medienprojekte.\n\n"
            "Die Audiodatei wurde mit KI-Technologie erstellt, die ausschließlich auf "
            "Open-Source- und Public-Domain-Datensätzen trainiert wurde. Der Lizenzinhaber "
            "darf diese Datei ohne Einschränkungen ändern, verteilen und monetarisieren.\n\n"
            "Diese Lizenz ist an den oben angegebenen Datei-Hash gebunden."
        )
        pdf.multi_cell(0, 5, txt=terms_de)
        pdf.ln(4)
        set_font("B", 10)
        pdf.cell(0, 8, txt="Ausgestellt von: Aegis Audio Pro", ln=True)

        # Страница 3: FR
        pdf.add_page()
        set_font("B", 22)
        pdf.cell(0, 14, txt="AEGIS AUDIO PRO", ln=True, align="C")
        set_font("B", 13)
        pdf.cell(0, 10, txt="CERTIFICAT DE LICENCE COMMERCIALE", ln=True, align="C")
        set_font("", 10)
        pdf.cell(0, 6, txt=f"Date de licence: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(0, 6, txt=f"Titulaire: {user_name}", ln=True)
        pdf.cell(0, 6, txt=f"Fichier audio: {audio_filename}", ln=True)
        pdf.cell(0, 6, txt=f"Empreinte: {file_hash[:32]}...", ln=True)
        pdf.ln(6)
        set_font("B", 12)
        pdf.cell(0, 10, txt="CONDITIONS DE LICENCE", ln=True)
        pdf.ln(2)
        set_font("", 10)
        terms_fr = (
            "Ce certificat accorde au titulaire une licence perpétuelle, mondiale, "
            "non exclusive et libre de redevances pour utiliser le fichier audio spécifié "
            "à des fins commerciales, y compris jeux vidéo, films, publicités et autres "
            "projets médiatiques.\n\n"
            "Le fichier a été généré par une IA entraînée exclusivement sur des jeux de "
            "données open source et du domaine public. Le titulaire est libre de modifier, "
            "distribuer et monétiser ce fichier sans restrictions.\n\n"
            "Cette licence est liée à l'empreinte du fichier ci-dessus."
        )
        pdf.multi_cell(0, 5, txt=terms_fr)
        pdf.ln(4)
        set_font("B", 10)
        pdf.cell(0, 8, txt="Émis par : Aegis Audio Pro", ln=True)

        # Страница 4: RU
        pdf.add_page()
        set_font("B", 22)
        pdf.cell(0, 14, txt="AEGIS AUDIO PRO", ln=True, align="C")
        set_font("B", 13)
        pdf.cell(0, 10, txt="СЕРТИФИКАТ КОММЕРЧЕСКОЙ ЛИЦЕНЗИИ", ln=True, align="C")
        set_font("", 10)
        pdf.cell(0, 6, txt=f"Дата лицензии: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(0, 6, txt=f"Лицензиат: {user_name}", ln=True)
        pdf.cell(0, 6, txt=f"Аудиофайл: {audio_filename}", ln=True)
        pdf.cell(0, 6, txt=f"Хеш: {file_hash[:32]}...", ln=True)
        pdf.ln(6)
        set_font("B", 12)
        pdf.cell(0, 10, txt="УСЛОВИЯ ЛИЦЕНЗИИ", ln=True)
        pdf.ln(2)
        set_font("", 10)
        terms_ru = (
            "Настоящий сертификат предоставляет Лицензиату бессрочную, всемирную, "
            "неисключительную, безвозмездную лицензию на использование указанного аудиофайла "
            "в любых коммерческих целях, включая видеоигры, фильмы, рекламу, стриминговый "
            "контент и другие медиа-проекты.\n\n"
            "Аудиофайл сгенерирован с использованием ИИ, обученного исключительно на "
            "открытых и общественных датасетах. Лицензиат вправе модифицировать, "
            "распространять и монетизировать файл без ограничений и требований указания "
            "авторства.\n\n"
            "Лицензия привязана к указанному выше хешу файла и не может быть передана."
        )
        pdf.multi_cell(0, 5, txt=terms_ru)
        pdf.ln(4)
        set_font("B", 10)
        pdf.cell(0, 8, txt="Выдано: Aegis Audio Pro", ln=True)

        pdf_filename = f"license_{audio_filename.replace('.wav', '').replace('.mp3', '').replace('.ogg', '').replace('.flac', '')}.pdf"
        pdf.output(pdf_filename)

        if qr_path and os.path.exists(qr_path):
            try:
                os.remove(qr_path)
            except:
                pass

        return pdf_filename

    @staticmethod
    def create_package(audio_filename, pdf_filename):
        zip_filename = f"AegisAudio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write(audio_filename)
            zipf.write(pdf_filename)
        os.remove(audio_filename)
        os.remove(pdf_filename)
        return zip_filename

    @staticmethod
    def create_game_ready_package(audio_filename, zip_filename, prompt, bpm, key):
        """Создаёт папку для Godot/Unity с .meta файлами"""
        game_dir = f"GameReady_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(game_dir, exist_ok=True)

        shutil.copy(audio_filename, os.path.join(game_dir, os.path.basename(audio_filename)))

        guid = hashlib.md5(audio_filename.encode()).hexdigest()[:32]
        # Unity .meta — {} экранированы как {{}}
        meta_content = (
            "fileFormatVersion: 2\n"
            f"guid: {guid}\n"
            "AudioImporter:\n"
            "  externalObjects: {}\n"
            "  serializedVersion: 6\n"
            "  defaultSettings:\n"
            "    loadType: 0\n"
            "    sampleRateSetting: 0\n"
            "    sampleRateOverride: 44100\n"
            "    compressionFormat: 1\n"
            "    quality: 1\n"
            "  platformSettingOverrides: {}\n"
            "  loadType: 0\n"
            "  forceToMono: 0\n"
            "  normalize: 1\n"
            "  preloadAudioData: 1\n"
            "  loadInBackground: 0\n"
            "  ambisonic: 0\n"
            "  3D: 1\n"
            "  userData: \n"
            "  assetBundleName: \n"
            "  assetBundleVariant: \n"
        )
        with open(os.path.join(game_dir, os.path.basename(audio_filename) + ".meta"), 'w') as f:
            f.write(meta_content)

        # Godot .import
        godot_import = (
            "[remap]\n\n"
            'importer="wav"\n'
            'type="AudioStreamSample"\n'
            f'path="res://.import/{os.path.basename(audio_filename)}-{guid[:8]}.sample"\n\n'
            "[deps]\n\n"
            f'source_file="{audio_filename}"\n'
            f'dest_paths=[ "res://audio/{os.path.basename(audio_filename)}" ]\n'
        )
        with open(os.path.join(game_dir, os.path.basename(audio_filename) + ".import"), 'w') as f:
            f.write(godot_import)

        # README
        readme = (
            "# Game Ready Audio Package\n\n"
            "Generated by Aegis Audio Pro\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "## Track Info\n"
            f"- Prompt: {prompt}\n"
            f"- BPM: {bpm or 'N/A'}\n"
            f"- Key: {key or 'N/A'}\n"
            "- License: Commercial (perpetual, worldwide)\n\n"
            "## How to Use\n\n"
            "### Unity\n"
            "Drop this folder into Assets/. The .meta file will be recognized automatically.\n\n"
            "### Godot\n"
            "Drop this folder into your project root. The .import file will be processed.\n\n"
            "## License\n"
            "This audio file is royalty-free for commercial use. See the included PDF license\n"
            "for full terms in 4 languages (EN/DE/FR/RU).\n\n"
            "Verify authenticity by scanning the QR code on the license's first page.\n"
        )
        with open(os.path.join(game_dir, "README.md"), 'w') as f:
            f.write(readme)

        if os.path.exists(zip_filename):
            shutil.copy(zip_filename, os.path.join(game_dir, "license_package.zip"))

        return game_dir


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
        self.chat_display.insert("1.0", "Привет! Я AI-ассистент Aegis Audio.\n\nКоманды (рус/eng):\n• 'обрежь до 20 секунд'\n• 'добавь фейд ин'\n• 'сделай громче на 50%'\n• 'луп' / 'loop'\n• 'реверс' / 'reverse'\n• 'реверб' / 'reverb'\n• 'бас' / 'bass boost'\n• 'питч +2' / 'pitch +2'\n• 'мастер' / 'master'\n• 'сайдчейн' / 'sidechain'\n• 'винил' / 'vinyl'\n• 'экв низ +3' / 'eq low +3'\n• 'стата' / 'stats'\n• 'аккорды' / 'chords'\n• 'стемы' / 'stems'\n• 'гейм' / 'game export'\n")

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
                    return f"Трек уже короче {seconds}с"
                return "Укажи: 'обрежь до 20 секунд'"
            elif "fade in" in command:
                match = re.search(r'(\d+)', command)
                sec = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_in_sec=sec)
                return f"✅ Fade in ({sec}с)"
            elif "fade out" in command:
                match = re.search(r'(\d+)', command)
                sec = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_out_sec=sec)
                return f"✅ Fade out ({sec}с)"
            elif "louder" in command:
                match = re.search(r'(\d+)', command)
                percent = int(match.group(1)) / 100.0 if match else 0.5
                self.app.current_audio *= (1.0 + percent)
                peak = np.max(np.abs(self.app.current_audio))
                if peak > 1.0:
                    self.app.current_audio /= peak
                return f"✅ Громкость +{percent*100:.0f}%"
            elif "loop" in command:
                loop_fade = int(2 * SAMPLE_RATE)
                fade_out = np.linspace(1.0, 0.0, loop_fade)
                fade_in = np.linspace(0.0, 1.0, loop_fade)
                self.app.current_audio[:loop_fade] = self.app.current_audio[:loop_fade] * fade_in + self.app.current_audio[-loop_fade:] * fade_out
                self.app.current_audio[-loop_fade:] = self.app.current_audio[-loop_fade:] * fade_out + self.app.current_audio[:loop_fade] * fade_in
                return "✅ Loop mode"
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
                match = re.search(r'([+-]?\d+)', command)
                semitones = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_pitch_shift(self.app.current_audio, semitones)
                return f"✅ Питч {semitones:+d}"
            elif "master" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_auto_master(self.app.current_audio)
                return "✅ Авто-мастеринг"
            elif "sidechain" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_sidechain_ducking(self.app.current_audio)
                return "✅ Сайдчейн — эффект 'дыхания'"
            elif "vinyl" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_vinyl_effect(self.app.current_audio)
                return "✅ Винил — тёплый lo-fi звук"
            elif "eq" in command:
                match = re.search(r'(low|mid|high|низ|сер|выс)\s*([+-]?\d+)', command)
                if match:
                    band_ru = match.group(1)
                    band = "low" if band_ru in ["low", "низ"] else "mid" if band_ru in ["mid", "сер"] else "high"
                    gain = int(match.group(2))
                    low = gain if band == "low" else 0
                    mid = gain if band == "mid" else 0
                    high = gain if band == "high" else 0
                    self.app.current_audio = MusicLicenseGenerator.apply_eq_3band(self.app.current_audio, low, mid, high)
                    return f"✅ EQ {band} {gain:+d}dB"
                return "Используй: 'экв низ +3'"
            elif "normalize" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_normalize(self.app.current_audio)
                return "✅ Нормализация"
            elif "harmon" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_harmonizer(self.app.current_audio)
                return "✅ Гармонизатор"
            elif "stems" in command or "separate" in command:
                return "🎵 Кнопка 'Stems' в панели эффектов"
            elif "game_export" in command:
                self.app._export_game_ready()
                return "✅ Game Ready пакет создан (Godot + Unity)"
            elif "stats" in command:
                analytics = MusicLicenseGenerator.get_audio_analytics(self.app.current_audio)
                return f"📊 Длит: {analytics['duration']}с | RMS: {analytics['rms']} | Пик: {analytics['peak']} | DR: {analytics['dynamic_range_db']}dB"
            elif "chord" in command:
                text = "🎵 Прогрессии:\n"
                for name, roman, notes in CHORD_PROGRESSIONS:
                    text += f"• {name}: {roman} ({notes})\n"
                return text
            elif "export" in command or "mp3" in command:
                if LICENSE_MODE == "PRO":
                    return "🎵 MP3 доступен. Кнопки скачивания под генерацией."
                return "⚠️ MP3 — PRO функция. Введи промокод в настройках."
            else:
                return "Не понял. Попробуй: 'обрежь до 20с', 'реверб', 'сайдчейн', 'винил', 'мастер', 'стата'"
        except Exception as e:
            return f"❌ Ошибка: {e}"


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.geometry("440x640")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        ctk.CTkLabel(self, text="⚙️ Settings", font=("Segoe UI Variable Display", 24, "bold"), text_color=T["text_primary"]).pack(pady=(20, 16))

        lang_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        lang_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(lang_frame, text="🌐 Language", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        lang_btns = ctk.CTkFrame(lang_frame, fg_color="transparent")
        lang_btns.pack(fill="x", padx=15, pady=(0, 12))
        for lang_code, lang_name, flag in [("ru", "Русский", "🇷🇺"), ("en", "English", "🇬🇧")]:
            ctk.CTkButton(lang_btns, text=f"{flag} {lang_name}", width=160, height=36, corner_radius=8, fg_color=T["accent"] if CURRENT_LANG == lang_code else T["card"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12), command=lambda l=lang_code: self._set_lang(l)).pack(side="left", padx=5, expand=True)

        theme_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        theme_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(theme_frame, text="🎨 Theme", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        theme_btns = ctk.CTkFrame(theme_frame, fg_color="transparent")
        theme_btns.pack(fill="x", padx=15, pady=(0, 12))
        for theme_name in ["dark", "light", "midnight"]:
            ctk.CTkButton(theme_btns, text=theme_name.capitalize(), width=110, height=36, corner_radius=8, fg_color=T["accent"] if CURRENT_THEME == theme_name else T["card"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12), command=lambda t=theme_name: self._set_theme(t)).pack(side="left", padx=5, expand=True)

        promo_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        promo_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(promo_frame, text="🎟️ Promo Code", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        promo_row = ctk.CTkFrame(promo_frame, fg_color="transparent")
        promo_row.pack(fill="x", padx=15, pady=(0, 12))
        self.promo_entry = ctk.CTkEntry(promo_row, placeholder_text="BETA2026", fg_color=T["card"], border_color=T["border"], border_width=1, corner_radius=8, height=36)
        self.promo_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(promo_row, text=tr("apply_code"), width=110, height=36, corner_radius=8, fg_color=T["success"], hover_color="#2BA84A", text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._apply_promo).pack(side="right")

        lic_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        lic_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(lic_frame, text="🔐 License Status", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        status_text = tr("code_active") if LICENSE_MODE == "PRO" else tr("code_inactive")
        status_color = T["success"] if LICENSE_MODE == "PRO" else T["warning"]
        ctk.CTkLabel(lic_frame, text=status_text, font=("Segoe UI", 14, "bold"), text_color=status_color).pack(anchor="w", padx=15, pady=(0, 12))

        stats = self.app.db.get_stats()
        stats_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        stats_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(stats_frame, text="📊 Statistics", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        ctk.CTkLabel(stats_frame, text=f"Total: {stats['total']} | Favorites: {stats['favorites']}", font=("Segoe UI", 12), text_color=T["text_secondary"]).pack(anchor="w", padx=15, pady=(0, 12))

        about_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        about_frame.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(about_frame, text="ℹ️ About", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(12, 8))
        ctk.CTkLabel(about_frame, text="Aegis Audio Pro v2.0\nMultilingual licensing (EN/DE/FR/RU)\nQR verification | Game Ready export", font=("Segoe UI", 11), text_color=T["text_secondary"], justify="left").pack(anchor="w", padx=15, pady=(0, 12))

        ctk.CTkButton(self, text="Close", height=44, corner_radius=12, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 14, "bold"), command=self.destroy).pack(pady=16)

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

    def _apply_promo(self):
        global LICENSE_MODE
        code = self.promo_entry.get().strip().upper()
        if code in PROMO_CODES:
            LICENSE_MODE = PROMO_CODES[code]
            self.app.set_status(tr("code_success"))
            self.app.license_label.configure(text=f"[{LICENSE_MODE}]", text_color=T["success"])
            self._build()
        else:
            self.app.set_status(tr("code_fail"))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aegis Audio Pro")
        self.geometry("1280x1020")
        self.resizable(True, True)
        self.configure(fg_color=T["app"])
        self.is_fullscreen = False
        self.start_time = datetime.now()
        try:
            self.iconbitmap("app.ico")
        except:
            pass
        self.db = Database()
        self.generator = MusicLicenseGenerator(status_callback=self.set_status, progress_callback=self.set_progress)
        self.model_loaded = False
        self.current_audio = None
        self.current_audio_path = None
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
        self.license_label = ctk.CTkLabel(title_row, text=f"[{LICENSE_MODE}]", font=("Segoe UI", 12, "bold"), text_color=T["success"] if LICENSE_MODE == "PRO" else T["warning"])
        self.license_label.pack(side="right", padx=(0, 10))
        ctk.CTkButton(title_row, text="🤖 AI", width=60, height=30, corner_radius=8, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 12, "bold"), command=self._toggle_ai_assistant).pack(side="right", padx=(0, 10))
        ctk.CTkButton(title_row, text="⚙️", width=40, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._open_settings).pack(side="right", padx=(0, 10))
        self.fs_btn = ctk.CTkButton(title_row, text="⛶", width=40, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._toggle_fullscreen).pack(side="right", padx=(0, 10))
        self.counter_label = ctk.CTkLabel(title_row, text=f"{self.track_count} {tr('tracks')}", font=("Segoe UI", 12), text_color=T["text_dim"])
        self.counter_label.pack(side="right", pady=6)
        ctk.CTkLabel(header, text="Royalty-free AI audio • Multilingual licenses • QR verified", font=("Segoe UI", 13), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(0, 18))

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

        prompt_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        prompt_card.pack(fill="x", pady=(0, 14))
        prompt_header = ctk.CTkFrame(prompt_card, fg_color="transparent")
        prompt_header.pack(fill="x", padx=22, pady=(16, 8))
        ctk.CTkLabel(prompt_header, text=tr("description"), font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(side="left")
        ctk.CTkButton(prompt_header, text=tr("random"), width=110, height=28, corner_radius=14, font=("Segoe UI", 11), fg_color=T["accent_light"], hover_color=T["accent_hover"], text_color=T["accent"], command=self._random_prompt).pack(side="right")
        self.prompt_box = ctk.CTkTextbox(prompt_card, height=92, corner_radius=14, font=("Segoe UI", 13), wrap="word", fg_color=T["card_hover"], border_color=T["border"], border_width=1)
        self.prompt_box.pack(fill="x", padx=22, pady=(0, 10))
        self.prompt_box.insert("1.0", PRESETS["Trap"]["prompt"])

        bpm_key_row = ctk.CTkFrame(prompt_card, fg_color="transparent")
        bpm_key_row.pack(fill="x", padx=22, pady=(0, 10))
        ctk.CTkLabel(bpm_key_row, text=tr("bpm_field"), font=("Segoe UI", 12)).pack(side="left")
        self.bpm_entry = ctk.CTkEntry(bpm_key_row, width=70, placeholder_text="120", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=8)
        self.bpm_entry.pack(side="left", padx=(8, 16))
        ctk.CTkLabel(bpm_key_row, text=tr("key_field"), font=("Segoe UI", 12)).pack(side="left")
        self.key_entry = ctk.CTkEntry(bpm_key_row, width=90, placeholder_text="A minor", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=8)
        self.key_entry.pack(side="left", padx=8)

        chips_frame = ctk.CTkFrame(prompt_card, fg_color="transparent")
        chips_frame.pack(fill="x", padx=22, pady=(0, 18))
        for name, data in PRESETS.items():
            chip = ctk.CTkButton(chips_frame, text=name, width=100, height=30, corner_radius=15, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], font=("Segoe UI", 11), command=lambda t=data["prompt"]: self._set_prompt(t))
            chip.pack(side="left", padx=(0, 6))
            desc = PRESET_DESCRIPTIONS.get(name, "")
            if desc:
                chip.bind("<Button-3>", lambda e, d=desc: self._show_tooltip(e, d))

        settings_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        settings_card.pack(fill="x", pady=(0, 14))
        self._add_slider_row(settings_card, tr("duration"), 5, 120, 10, self._update_duration_label)
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
        self.download_ogg_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.game_ready_btn = ctk.CTkButton(download_frame, text=tr("game_ready"), height=40, corner_radius=12, font=("Segoe UI", 12, "bold"), fg_color=T["success"], hover_color="#2BA84A", text_color="#FFFFFF", command=self._export_game_ready, state="disabled")
        self.game_ready_btn.pack(side="left", fill="x", expand=True)

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
            ("Auto Master", "master"), ("Harmonizer", "harmonizer"), ("Spectral Gate", "gate"), ("Sidechain", "sidechain"),
            ("Vinyl", "vinyl"), ("A/B Compare", "ab"), ("Undo", "undo"), ("Redo", "redo"),
            ("Copy Hash", "copy_hash"), ("Stems", "stems"),
        ]
        for i, (text, cmd) in enumerate(effect_buttons):
            row_idx = i // 4
            col_idx = i % 4
            btn = ctk.CTkButton(effects_grid, text=text, width=180, height=48, corner_radius=12, fg_color=T["card_hover"], hover_color=T["accent"], text_color=T["text_primary"], font=("Segoe UI", 14, "bold"), command=lambda c=cmd: self._handle_effect(c))
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

    def _toggle_ai_assistant(self):
        if self.ai_assistant.is_expanded:
            self.ai_assistant._collapse()
        else:
            self.ai_assistant._expand()

    def _quick_download(self, format):
        if not self.current_audio:
            self.set_status(tr("no_track"))
            return
        try:
            if format == "mp3" and LICENSE_MODE == "FREE":
                from tkinter import messagebox
                messagebox.showinfo("PRO feature", "MP3 export is PRO only. Enter promo code in Settings.")
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

    def _export_game_ready(self):
        if not self.current_audio or not self.current_audio_path:
            self.set_status(tr("generate_first"))
            return
        try:
            prompt = self.prompt_box.get("1.0", "end").strip()
            bpm = self.generator.detect_bpm(self.current_audio)
            key = self.generator.detect_key(self.current_audio)
            zip_file = None
            for h in self.history:
                if h.get("file") and os.path.exists(h["file"]):
                    zip_file = h["file"]
                    break
            if not zip_file:
                zip_file = "no_license.zip"
            game_dir = MusicLicenseGenerator.create_game_ready_package(
                self.current_audio_path, zip_file, prompt, bpm, key
            )
            self.set_status(f"🎮 Game Ready package: {game_dir}")
            os.startfile(game_dir)
        except Exception as e:
            self.set_status(f"Game export error: {str(e)}")

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
        x = event.x_root + 14
        y = event.y_root + 14
        tw.geometry(f"+{x}+{y}")
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
        except:
            prompt = ""
        try:
            dur = self.duration_slider.get()
            temp = self.temp_slider.get()
            guid = self.guidance_slider.get()
        except:
            dur, temp, guid = 10, 1.0, 3.0
        try:
            user = self.user_entry.get()
        except:
            user = ""
        try:
            bpm_val = self.bpm_entry.get()
            key_val = self.key_entry.get()
        except:
            bpm_val, key_val = "", ""
        try:
            info = self.result_text.cget("text")
        except:
            info = tr("empty_result")
        try:
            meta = self.meta_text.cget("text")
        except:
            meta = "BPM: -- | Key: -- | Duration: -- | RMS: --"
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
            self.bpm_entry.delete(0, "end")
            self.bpm_entry.insert(0, bpm_val)
            self.key_entry.delete(0, "end")
            self.key_entry.insert(0, key_val)
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
                self.play_btn.configure(state="normal")
                self.save_btn.configure(state="normal")
                self.export_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.download_wav_btn.configure(state="normal")
                self.download_mp3_btn.configure(state="normal")
                self.download_ogg_btn.configure(state="normal")
                self.game_ready_btn.configure(state="normal")
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
        elif cmd == "game_export":
            self._export_game_ready()
        else:
            self._apply_effect(cmd)

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.attributes("-fullscreen", True)
            self.fs_btn.configure(text="✕")
        else:
            self.attributes("-fullscreen", False)
            self.fs_btn.configure(text="⛶")

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
            elif effect == "sidechain":
                audio = MusicLicenseGenerator.apply_sidechain_ducking(audio)
            elif effect == "vinyl":
                audio = MusicLicenseGenerator.apply_vinyl_effect(audio)
            self.current_audio = audio
            self._draw_waveform(audio)
            self.set_status(f"{tr('applied')}: {effect}")
        except Exception as e:
            err_msg = str(e)
            self.set_status(f"{tr('effect_error')}: {err_msg}")

    def _separate_stems(self):
        if not self.current_audio:
            self.set_status(tr("generate_first"))
            return
        self._save_undo_state()
        stems = MusicLicenseGenerator.separate_stems_simple(np.squeeze(self.current_audio))
        for name, stem in stems.items():
            filename = f"stem_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            sf.write(filename, stem, SAMPLE_RATE)
        self.set_status(f"Stems saved: bass, mid, high")

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
        self.play_btn.configure(text="🆚 A/B Playing...")
        self.set_status("A/B Compare: Original → Current")

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
        bpm_text = self.bpm_entry.get().strip()
        key_text = self.key_entry.get().strip()
        if bpm_text:
            prompt += f", {bpm_text} bpm"
        if key_text:
            prompt += f", in {key_text}"
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
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.download_wav_btn.configure(state="disabled")
        self.download_mp3_btn.configure(state="disabled")
        self.download_ogg_btn.configure(state="disabled")
        self.game_ready_btn.configure(state="disabled")
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
                self.set_progress(int((i + 1) / batch_count * 90))
            self.original_audio = best_audio.copy()
            self.current_audio = best_audio
            self._save_undo_state()
            wav = self.generator.save_wav(best_audio)
            self.current_audio_path = wav
            file_hash = self.generator.calculate_hash(wav)
            bpm = self.generator.detect_bpm(best_audio)
            key = self.generator.detect_key(best_audio)
            analytics = self.generator.get_audio_analytics(best_audio)
            license_type = "Commercial" if LICENSE_MODE == "PRO" else "Personal"
            pdf = self.generator.generate_license_pdf(wav, file_hash, user_name, license_type, bpm, key, analytics)
            zip_file = self.generator.create_package(wav, pdf)
            self.track_count += 1
            dur_str = f"{duration//60}:{duration%60:02d}" if duration >= 60 else f"{duration}s"
            rms_val = analytics['rms']
            peak_val = analytics['peak']
            dr_val = analytics['dynamic_range_db']
            file_size = os.path.getsize(zip_file) // 1024
            info = (f"File: {zip_file}\nDuration: {dur_str}\nLicensee: {user_name}\nLicense: {license_type} (EN/DE/FR/RU)\nBPM: {bpm or '--'} | Key: {key or '--'}\nRMS: {rms_val} | Peak: {peak_val}\nDynamic Range: {dr_val} dB\nTemp: {temperature:.1f} | Guidance: {guidance_scale:.1f}\nSHA-256: {file_hash[:32]}...\nSize: {file_size} KB\nQR verification: scan license page 1")
            if seed is not None:
                info += f"\nSeed: {seed}"
            if batch_count > 1:
                info += f"\nVariants generated: {batch_count}"
            preview_samples = best_audio[::100]
            preview_str = ",".join(f"{v:.2f}" for v in preview_samples[:200])
            track_id = self.db.add_track(
                prompt=prompt, duration=duration, bpm=bpm, key=key,
                rms=analytics['rms'], peak=analytics['peak'],
                dynamic_range=analytics['dynamic_range_db'],
                license_type=license_type, licensee=user_name,
                file_hash=file_hash, file_path=zip_file,
                seed=seed, temperature=temperature, guidance_scale=guidance_scale,
                loop_mode=1 if loop_mode else 0, audio_preview=preview_str
            )
            self.history.insert(0, {"id": track_id, "time": datetime.now().strftime("%H:%M"), "prompt": prompt[:60] + "..." if len(prompt) > 60 else prompt, "duration": dur_str, "file": zip_file, "bpm": bpm, "hash": file_hash, "favorite": False, "preview": preview_str})
            self.history = self.history[:20]
            def done():
                self.result_text.configure(text=info, text_color=T["text_primary"])
                self.meta_text.configure(text=f"BPM: {bpm or '--'} | Key: {key or '--'} | Duration: {dur_str} | RMS: {rms_val} | Loop: {'Yes' if loop_mode else 'No'}", text_color=T["text_primary"])
                self.generate_btn.configure(state="normal", text=tr("generate"))
                self.play_btn.configure(state="normal")
                self.save_btn.configure(state="normal")
                self.export_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.download_wav_btn.configure(state="normal")
                self.download_mp3_btn.configure(state="normal")
                self.download_ogg_btn.configure(state="normal")
                self.game_ready_btn.configure(state="normal")
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
            "bpm": self.bpm_entry.get(),
            "key": self.key_entry.get(),
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
        export_path = filedialog.asksaveasfilename(title="Export audio", defaultextension=".wav", filetypes=[("WAV", "*.wav"), ("MP3", "*.mp3"), ("OGG", "*.ogg"), ("FLAC", "*.flac"), ("MIDI", "*.mid")])
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
                elif export_path.endswith(".flac"):
                    self.generator.save_flac(self.current_audio)
                elif export_path.endswith(".mid"):
                    midi_path = self.generator.save_midi(self.current_audio)
                    if midi_path:
                        self.set_status(f"MIDI exported: {midi_path}")
                    return
                else:
                    self.generator.save_wav(self.current_audio)
                self.set_status(f"{tr('exported')}: {export_path}")
            except Exception as e:
                err_msg = str(e)
                self.set_status(f"{tr('export_error')}: {err_msg}")

    def _update_history(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()
        query = self.search_var.get().lower()
        filtered = [e for e in self.history if not query or query in e["prompt"].lower()]
        if not filtered:
            self.history_empty.pack(expand=True, pady=40)
            return
        for idx, entry in enumerate(filtered):
            item = ctk.CTkFrame(self.history_scroll, fg_color=T["card_hover"], corner_radius=14, border_color=T["border"], border_width=1)
            item.pack(fill="x", pady=(0, 8))
            top_row = ctk.CTkFrame(item, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(top_row, text=entry["time"], font=("Segoe UI", 10, "bold"), text_color=T["accent"]).pack(side="left")
            fav_btn = ctk.CTkButton(top_row, text="⭐" if entry.get("favorite") else "☆", width=30, height=24, corner_radius=8, fg_color="transparent", hover_color=T["border"], text_color=T["warning"], font=("Segoe UI", 12), command=lambda e=entry: self._toggle_favorite(e))
            fav_btn.pack(side="right")
            if idx < 3 and entry.get("preview"):
                try:
                    preview_data = np.array([float(x) for x in entry["preview"].split(",")])
                    fig = plt.figure(figsize=(2.5, 0.5), dpi=60)
                    fig.patch.set_facecolor(T["card_hover"])
                    ax = fig.add_subplot(111)
                    ax.set_facecolor(T["card_hover"])
                    ax.plot(preview_data, color=T["waveform"], linewidth=0.5)
                    ax.axis('off')
                    ax.set_ylim(-1.1, 1.1)
                    canvas_mini = FigureCanvasTkAgg(fig, master=item)
                    canvas_mini.draw()
                    canvas_mini.get_tk_widget().pack(fill="x", padx=12, pady=(0, 2))
                except:
                    pass
            prompt_short = entry["prompt"][:60]
            ctk.CTkLabel(item, text=prompt_short, font=("Segoe UI", 11), text_color=T["text_primary"], wraplength=240, justify="left").pack(anchor="w", padx=12, pady=(0, 2))
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
            prompt_short = entry["prompt"][:40]
            ctk.CTkLabel(item, text=f"⭐ {prompt_short}...", font=("Segoe UI", 10), text_color=T["text_primary"], wraplength=260).pack(anchor="w", padx=10, pady=6)

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
