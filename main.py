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
import copy
import sqlite3
import time
from datetime import datetime
from fpdf import FPDF
import zipfile
import numpy as np
import customtkinter as ctk
import sounddevice as sd
from scipy.signal import butter, lfilter, fftconvolve, iirfilter, sosfilt
from scipy.ndimage import uniform_filter1d
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from pydub import AudioSegment
import pyperclip
import pretty_midi

# ===== PATH SETUP =====
if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# ===== THEMES =====
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
DB_PATH = "aegis_audio.db"

SAMPLE_RATE = 32000
NATIVE_CHUNK = 30
CONTEXT_TAIL = 10
CROSSFADE = 2

# ===== DATABASE =====
class Database:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_tables()

    def _init_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                prompt TEXT,
                duration REAL,
                bpm INTEGER,
                key TEXT,
                rms REAL,
                peak REAL,
                dynamic_range REAL,
                license_type TEXT,
                licensee TEXT,
                file_hash TEXT,
                file_path TEXT,
                favorite INTEGER DEFAULT 0,
                seed INTEGER,
                temperature REAL,
                guidance_scale REAL,
                loop_mode INTEGER DEFAULT 0
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                settings TEXT,
                created_at TEXT
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS render_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT,
                duration REAL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                completed_at TEXT
            )
        ''')
        self.conn.commit()

    def add_track(self, **kwargs):
        self.cursor.execute('''
            INSERT INTO tracks (timestamp, prompt, duration, bpm, key, rms, peak, 
            dynamic_range, license_type, licensee, file_hash, file_path, favorite,
            seed, temperature, guidance_scale, loop_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            kwargs.get('timestamp', datetime.now().isoformat()),
            kwargs.get('prompt', ''),
            kwargs.get('duration', 0),
            kwargs.get('bpm'),
            kwargs.get('key'),
            kwargs.get('rms'),
            kwargs.get('peak'),
            kwargs.get('dynamic_range'),
            kwargs.get('license_type', 'Personal'),
            kwargs.get('licensee', 'User'),
            kwargs.get('file_hash', ''),
            kwargs.get('file_path', ''),
            kwargs.get('favorite', 0),
            kwargs.get('seed'),
            kwargs.get('temperature', 1.0),
            kwargs.get('guidance_scale', 3.0),
            kwargs.get('loop_mode', 0)
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_tracks(self, limit=50, favorite_only=False, search=None):
        query = "SELECT * FROM tracks WHERE 1=1"
        params = []
        if favorite_only:
            query += " AND favorite = 1"
        if search:
            query += " AND prompt LIKE ?"
            params.append(f"%{search}%")
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def toggle_favorite(self, track_id):
        self.cursor.execute("UPDATE tracks SET favorite = NOT favorite WHERE id = ?", (track_id,))
        self.conn.commit()

    def delete_track(self, track_id):
        self.cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        self.conn.commit()

    def save_preset(self, name, settings):
        self.cursor.execute('''
            INSERT OR REPLACE INTO presets (name, settings, created_at)
            VALUES (?, ?, ?)
        ''', (name, json.dumps(settings), datetime.now().isoformat()))
        self.conn.commit()

    def get_presets(self):
        self.cursor.execute("SELECT * FROM presets ORDER BY created_at DESC")
        return self.cursor.fetchall()

    def load_preset(self, name):
        self.cursor.execute("SELECT settings FROM presets WHERE name = ?", (name,))
        row = self.cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None

    def delete_preset(self, name):
        self.cursor.execute("DELETE FROM presets WHERE name = ?", (name,))
        self.conn.commit()

    def add_to_queue(self, prompt, duration):
        self.cursor.execute('''
            INSERT INTO render_queue (prompt, duration, status, created_at)
            VALUES (?, ?, 'pending', ?)
        ''', (prompt, duration, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_queue(self):
        self.cursor.execute("SELECT * FROM render_queue WHERE status != 'completed' ORDER BY id")
        return self.cursor.fetchall()

    def update_queue_status(self, queue_id, status):
        self.cursor.execute('''
            UPDATE render_queue SET status = ?, completed_at = ? WHERE id = ?
        ''', (status, datetime.now().isoformat() if status == 'completed' else None, queue_id))
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM tracks")
        total = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM tracks WHERE favorite = 1")
        favorites = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT AVG(duration) FROM tracks")
        avg_dur = self.cursor.fetchone()[0] or 0
        return {"total": total, "favorites": favorites, "avg_duration": round(avg_dur, 1)}


# ===== MUSIC GENERATOR =====
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

    # ===== SAVE FORMATS =====
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
    def save_midi(audio, samplerate=SAMPLE_RATE, min_freq=50, max_freq=2000):
        """Конвертация аудио в MIDI через анализ пиков частот"""
        try:
            import librosa
            pitches, magnitudes = librosa.piptrack(y=audio, sr=samplerate)
            midi_notes = []
            threshold = np.median(magnitudes) * 2
            for t in range(pitches.shape[1]):
                for f in range(pitches.shape[0]):
                    if magnitudes[f, t] > threshold and min_freq < pitches[f, t] < max_freq:
                        midi_note = librosa.hz_to_midi(pitches[f, t])
                        midi_notes.append((t * 512 / samplerate, int(round(midi_note)), 100))
                        break
            midi = pretty_midi.PrettyMIDI()
            piano = pretty_midi.Instrument(program=0)
            if midi_notes:
                midi_notes.sort(key=lambda x: x[0])
                start = midi_notes[0][0]
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

    # ===== ANALYSIS =====
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
        return {
            "rms": round(rms, 4), "peak": round(peak, 4),
            "duration": round(duration, 2), "dynamic_range_db": round(dynamic_range, 2),
            "samples": len(audio), "sample_rate": sr
        }

    @staticmethod
    def get_frequency_bands(audio, sr=SAMPLE_RATE):
        """Анализ частотных полос: sub/bass/mid/high/air"""
        try:
            spectrum = np.abs(np.fft.rfft(audio))
            freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
            bands = {
                "sub (20-60Hz)": np.mean(spectrum[(freqs >= 20) & (freqs < 60)]) if np.any((freqs >= 20) & (freqs < 60)) else 0,
                "bass (60-250Hz)": np.mean(spectrum[(freqs >= 60) & (freqs < 250)]) if np.any((freqs >= 60) & (freqs < 250)) else 0,
                "mid (250-2kHz)": np.mean(spectrum[(freqs >= 250) & (freqs < 2000)]) if np.any((freqs >= 250) & (freqs < 2000)) else 0,
                "high (2k-8kHz)": np.mean(spectrum[(freqs >= 2000) & (freqs < 8000)]) if np.any((freqs >= 2000) & (freqs < 8000)) else 0,
                "air (8k+)": np.mean(spectrum[freqs >= 8000]) if np.any(freqs >= 8000) else 0
            }
            return bands
        except:
            return None

    # ===== AUDIO EFFECTS =====
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
        output = audio.copy()
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
    def apply_trim(audio, start_sec, end_sec):
        start = int(start_sec * SAMPLE_RATE)
        end = int(end_sec * SAMPLE_RATE)
        return audio[start:end].copy()

    @staticmethod
    def apply_volume_automation(audio, points):
        if not points:
            return audio
        times = [p[0] for p in points]
        volumes = [p[1] for p in points]
        total_samples = len(audio)
        total_sec = total_samples / SAMPLE_RATE
        envelope = np.interp(np.linspace(0, total_sec, total_samples), times, volumes)
        return audio * envelope

    @staticmethod
    def apply_eq_3band(audio, low_gain_db=0, mid_gain_db=0, high_gain_db=0):
        """3-полосный эквалайзер: low/mid/high"""
        result = audio.copy()
        nyq = SAMPLE_RATE / 2
        # Low: 20-300Hz
        if low_gain_db != 0:
            b, a = butter(2, 300 / nyq, btype='low')
            low_band = lfilter(b, a, result)
            gain = 10 ** (low_gain_db / 20)
            result = result + low_band * (gain - 1)
        # Mid: 300-3000Hz
        if mid_gain_db != 0:
            b1, a1 = butter(2, 300 / nyq, btype='high')
            b2, a2 = butter(2, 3000 / nyq, btype='low')
            mid_band = sosfilt((b2, a2), sosfilt((b1, a1), result))
            gain = 10 ** (mid_gain_db / 20)
            result = result + mid_band * (gain - 1)
        # High: 3000+ Hz
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
        """Компрессор для мастеринга"""
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
        """Лимитер для предотвращения клиппинга"""
        ceiling = 10 ** (ceiling_db / 20)
        return np.clip(audio, -ceiling, ceiling)

    @staticmethod
    def apply_auto_master(audio):
        """Автоматический мастеринг: компрессор + лимитер + нормализация"""
        compressed = MusicLicenseGenerator.apply_compressor(audio, threshold=-18, ratio=3.0)
        limited = MusicLicenseGenerator.apply_limiter(compressed, ceiling_db=-0.5)
        normalized = MusicLicenseGenerator.apply_normalize(limited, target_db=-3)
        return normalized

    @staticmethod
    def apply_spectral_gate(audio, threshold_db=-40):
        """Шумоподавление через спектральный гейт"""
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
        """Добавление гармоний (октавы, квинты)"""
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
    def apply_stereo_widen(audio):
        """Псевдо-стерео расширение через задержку"""
        if len(audio) < SAMPLE_RATE:
            return audio
        delay = int(0.02 * SAMPLE_RATE)
        left = audio
        right = np.roll(audio, delay)
        right[:delay] = 0
        stereo = np.column_stack((left, right))
        return stereo

    @staticmethod
    def apply_vocal_remove(audio):
        """Удаление центрального канала (вокала)"""
        if len(audio) < 2:
            return audio
        mid = audio
        side = np.roll(audio, 1)
        side[0] = 0
        result = (mid - side) / 2
        return result

    @staticmethod
    def mix_tracks(tracks, volumes=None):
        """Микширование нескольких треков"""
        if not tracks:
            return None
        max_len = max(len(t) for t in tracks)
        result = np.zeros(max_len)
        for i, track in enumerate(tracks):
            vol = volumes[i] if volumes and i < len(volumes) else 1.0
            padded = np.zeros(max_len)
            padded[:len(track)] = track
            result += padded * vol
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result = result / peak
        return result

    @staticmethod
    def separate_stems_simple(audio):
        """Упрощённое разделение на bass/mid/high (псевдо-stems)"""
        nyq = SAMPLE_RATE / 2
        b_low, a_low = butter(2, 250 / nyq, btype='low')
        b_mid, a_mid = butter(2, [250 / nyq, 4000 / nyq], btype='band')
        b_high, a_high = butter(2, 4000 / nyq, btype='high')
        bass = lfilter(b_low, a_low, audio)
        mid = lfilter(b_mid, a_mid, audio)
        high = lfilter(b_high, a_high, audio)
        return {"bass": bass, "mid": mid, "high": high}

    @staticmethod
    def generate_license_pdf(audio_filename, file_hash, user_name, license_type="Commercial", bpm=None, key=None, analytics=None):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 18)
        pdf.cell(200, 12, txt="AEGIS AUDIO PRO", ln=True, align="C")
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 8, txt=f"{license_type} License Certificate", ln=True, align="C")
        pdf.ln(12)
        pdf.set_font("Arial", size=11)
        pdf.cell(200, 8, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(200, 8, txt=f"License Holder: {user_name}", ln=True)
        pdf.cell(200, 8, txt=f"Audio File: {audio_filename}", ln=True)
        if bpm:
            pdf.cell(200, 8, txt=f"BPM: {bpm}", ln=True)
        if key:
            pdf.cell(200, 8, txt=f"Key: {key}", ln=True)
        if analytics:
            pdf.cell(200, 8, txt=f"Duration: {analytics['duration']}s | RMS: {analytics['rms']}", ln=True)
        pdf.cell(200, 8, txt=f"License Type: {license_type}", ln=True)
        pdf.cell(200, 8, txt=f"File Hash (SHA-256):", ln=True)
        pdf.set_font("Courier", size=8)
        pdf.multi_cell(0, 4, file_hash)
        pdf.ln(8)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(200, 10, txt="LICENSE TERMS:", ln=True)
        pdf.ln(4)
        pdf.set_font("Arial", size=10)
        if license_type == "Commercial":
            license_text = """This certificate grants the License Holder a perpetual, worldwide, non-exclusive, royalty-free license to use the specified audio file for any commercial purpose, including but not limited to: video games, films, advertisements, streaming content, and other media projects.

The audio file was generated using AI technology trained exclusively on open-source and public domain datasets. The License Holder is free to modify, distribute, and monetize this audio file without any restrictions or attribution requirements.

This license is tied to the specific file hash above and cannot be transferred to other files.

Issued by: Aegis Audio Pro"""
        else:
            license_text = """This certificate grants the License Holder a non-exclusive license to use the specified audio file for personal, non-commercial purposes only.

Commercial use, redistribution, and monetization are NOT permitted under this license.

To upgrade to a Commercial License, please visit: https://aegis-audio.com/pro

Issued by: Aegis Audio Pro (Free Tier)"""
        pdf.multi_cell(0, 5, license_text)
        pdf_filename = f"license_{audio_filename.replace('.wav', '').replace('.mp3', '').replace('.ogg', '').replace('.flac', '')}.pdf"
        pdf.output(pdf_filename)
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


# ===== DYNAMIC ISLAND =====
class DynamicIsland(ctk.CTkFrame):
    def __init__(self, master, app_instance, **kwargs):
        super().__init__(master, fg_color=T["island"], corner_radius=20, height=40, **kwargs)
        self.app = app_instance
        self.is_expanded = False
        self.pack(fill="x", pady=(10, 0))
        self.indicator = ctk.CTkLabel(self, text="● AI Assistant", font=("Segoe UI", 12), text_color=T["island_text"])
        self.indicator.pack(expand=True)
        self.bind("<Button-1>", self._toggle)
        self.indicator.bind("<Button-1>", self._toggle)
        self.expanded_panel = None

    def _toggle(self, event=None):
        if self.is_expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self):
        self.is_expanded = True
        self.configure(height=500, fg_color="#FFFFFF", corner_radius=20)
        self.indicator.pack_forget()
        self.expanded_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.expanded_panel.pack(fill="both", expand=True, padx=20, pady=20)
        header = ctk.CTkFrame(self.expanded_panel, fg_color="transparent")
        header.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(header, text="AI Assistant", font=("Segoe UI Variable Display", 20, "bold"), text_color="#000000").pack(side="left")
        ctk.CTkButton(header, text="✕", width=30, height=30, corner_radius=15, fg_color="#2A2A2A", hover_color="#1A1A1A", text_color="#FFFFFF", font=("Segoe UI", 14), command=self._collapse).pack(side="right")
        chat_frame = ctk.CTkFrame(self.expanded_panel, fg_color="#1A1A1A", corner_radius=12)
        chat_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.chat_display = ctk.CTkTextbox(chat_frame, height=200, corner_radius=12, font=("Segoe UI", 12), wrap="word", fg_color="#1A1A1A", text_color="#FFFFFF")
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=10)
        self.chat_display.insert("1.0", "Hi! I'm your AI assistant.\n\nCommands:\n• 'trim to 20 seconds'\n• 'add fade in/out'\n• 'make louder 50%'\n• 'loop mode'\n• 'reverse'\n• 'reverb'\n• 'bass boost'\n• 'pitch +2'\n• 'master'\n• 'eq low +3'\n• 'stats'\n• 'chords'\n• 'stems'\n")
        input_frame = ctk.CTkFrame(self.expanded_panel, fg_color="transparent")
        input_frame.pack(fill="x")
        self.chat_input = ctk.CTkEntry(input_frame, placeholder_text="Type command...", fg_color="#1A1A1A", border_color="#333333", border_width=1, corner_radius=10, text_color="#FFFFFF")
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.chat_input.bind("<Return>", lambda e: self._process_command())
        ctk.CTkButton(input_frame, text="Send", width=100, height=36, corner_radius=10, fg_color="#007AFF", hover_color="#0066CC", text_color="#FFFFFF", font=("Segoe UI", 12), command=self._process_command).pack(side="right")
        ctk.CTkButton(self, text="Collapse", height=30, corner_radius=10, fg_color="#2A2A2A", hover_color="#1A1A1A", text_color="#FFFFFF", font=("Segoe UI", 11), command=self._collapse).pack(pady=(10, 0))

    def _collapse(self):
        self.is_expanded = False
        self.configure(height=40, fg_color=T["island"])
        if self.expanded_panel:
            self.expanded_panel.destroy()
            self.expanded_panel = None
        self.indicator.configure(text_color=T["island_text"])
        self.indicator.pack(expand=True)

    def _process_command(self):
        command = self.chat_input.get().strip().lower()
        if not command:
            return
        self.chat_input.delete(0, "end")
        self.chat_display.insert("end", f"\nYou: {command}\n")
        response = self._handle_command(command)
        self.chat_display.insert("end", f"Assistant: {response}\n")
        self.chat_display.see("end")

    def _handle_command(self, command):
        if not self.app.current_audio:
            return "Generate a track first."
        try:
            if "trim" in command:
                match = re.search(r'(\d+)', command)
                if match:
                    seconds = int(match.group(1))
                    samples = seconds * SAMPLE_RATE
                    if len(self.app.current_audio) > samples:
                        self.app.current_audio = self.app.current_audio[:samples]
                        return f"✅ Trimmed to {seconds}s"
                    return f"Track already shorter than {seconds}s"
                return "Specify duration: 'trim to 20 seconds'"
            elif "fade in" in command:
                match = re.search(r'(\d+)', command)
                sec = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_in_sec=sec)
                return f"✅ Fade in added ({sec}s)"
            elif "fade out" in command:
                match = re.search(r'(\d+)', command)
                sec = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_fade(self.app.current_audio, fade_out_sec=sec)
                return f"✅ Fade out added ({sec}s)"
            elif "louder" in command:
                match = re.search(r'(\d+)', command)
                percent = int(match.group(1)) / 100.0 if match else 0.5
                self.app.current_audio *= (1.0 + percent)
                peak = np.max(np.abs(self.app.current_audio))
                if peak > 1.0:
                    self.app.current_audio /= peak
                return f"✅ Volume +{percent*100:.0f}%"
            elif "loop" in command:
                loop_fade = int(2 * SAMPLE_RATE)
                fade_out = np.linspace(1.0, 0.0, loop_fade)
                fade_in = np.linspace(0.0, 1.0, loop_fade)
                self.app.current_audio[:loop_fade] = self.app.current_audio[:loop_fade] * fade_in + self.app.current_audio[-loop_fade:] * fade_out
                self.app.current_audio[-loop_fade:] = self.app.current_audio[-loop_fade:] * fade_out + self.app.current_audio[:loop_fade] * fade_in
                return "✅ Loop mode applied"
            elif "reverse" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_reverse(self.app.current_audio)
                return "✅ Reversed"
            elif "reverb" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_reverb(self.app.current_audio)
                return "✅ Reverb applied"
            elif "delay" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_delay(self.app.current_audio)
                return "✅ Delay applied"
            elif "bass" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_bass_boost(self.app.current_audio)
                return "✅ Bass boost applied"
            elif "pitch" in command:
                match = re.search(r'([+-]?\d+)', command)
                semitones = int(match.group(1)) if match else 2
                self.app.current_audio = MusicLicenseGenerator.apply_pitch_shift(self.app.current_audio, semitones)
                return f"✅ Pitch shifted {semitones:+d} semitones"
            elif "master" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_auto_master(self.app.current_audio)
                return "✅ Auto-mastering applied (compressor + limiter + normalize)"
            elif "eq" in command:
                match = re.search(r'(low|mid|high)\s*([+-]?\d+)', command)
                if match:
                    band = match.group(1)
                    gain = int(match.group(2))
                    low = gain if band == "low" else 0
                    mid = gain if band == "mid" else 0
                    high = gain if band == "high" else 0
                    self.app.current_audio = MusicLicenseGenerator.apply_eq_3band(self.app.current_audio, low, mid, high)
                    return f"✅ EQ {band} {gain:+d}dB"
                return "Usage: 'eq low +3' or 'eq high -2'"
            elif "normalize" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_normalize(self.app.current_audio)
                return "✅ Normalized"
            elif "harmon" in command:
                self.app.current_audio = MusicLicenseGenerator.apply_harmonizer(self.app.current_audio)
                return "✅ Harmonizer applied"
            elif "stems" in command or "separate" in command:
                return "🎵 Use 'Stem Separation' button in Effects panel"
            elif "stats" in command:
                analytics = MusicLicenseGenerator.get_audio_analytics(self.app.current_audio)
                bands = MusicLicenseGenerator.get_frequency_bands(self.app.current_audio)
                text = f"📊 Analytics:\n• Duration: {analytics['duration']}s\n• RMS: {analytics['rms']}\n• Peak: {analytics['peak']}\n• Dynamic Range: {analytics['dynamic_range_db']} dB\n\n📈 Frequency Bands:\n"
                if bands:
                    for band, val in bands.items():
                        text += f"• {band}: {val:.2f}\n"
                return text
            elif "chord" in command:
                chords_text = "🎵 Popular progressions:\n"
                for name, roman, notes in CHORD_PROGRESSIONS:
                    chords_text += f"• {name}: {roman} ({notes})\n"
                return chords_text
            elif "export" in command or "mp3" in command:
                if LICENSE_MODE == "PRO":
                    return "🎵 MP3 export available. Use Export button."
                return "⚠️ MP3 export is PRO only"
            else:
                return "Unknown command. Try: 'trim to 20s', 'reverb', 'master', 'eq low +3', 'stats', 'stems'"
        except Exception as e:
            return f"❌ Error: {e}"


# ===== COMMAND PALETTE =====
class CommandPalette(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Command Palette")
        self.geometry("500x400")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Type command...", height=40, font=("Segoe UI", 14))
        self.search_entry.pack(fill="x", padx=10, pady=10)
        self.search_entry.bind("<KeyRelease>", self._filter)
        self.search_entry.focus_set()
        self.commands_list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.commands_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.all_commands = [
            ("⚡ Generate track", self.app._on_generate),
            ("📤 Export audio", self.app._export_audio),
            ("💾 Save project", self.app._save_project),
            ("🔄 Toggle loop mode", lambda: self.app.loop_var.set(not self.app.loop_var.get())),
            ("🎨 Switch theme", self.app._toggle_theme),
            ("🌐 Switch language", self.app._toggle_language),
            ("▶ Play/Stop", self.app._toggle_play),
            ("📂 Open folder", self.app._open_folder),
            ("🎛️ Apply reverb", lambda: self._apply_effect("reverb")),
            ("🎛️ Apply delay", lambda: self._apply_effect("delay")),
            ("🎛️ Bass boost", lambda: self._apply_effect("bass")),
            ("🎛️ Reverse", lambda: self._apply_effect("reverse")),
            ("🎛️ Normalize", lambda: self._apply_effect("normalize")),
            ("🎛️ Auto Master", lambda: self._apply_effect("master")),
            ("🎛️ Harmonizer", lambda: self._apply_effect("harmonizer")),
            ("🎛️ Spectral Gate", lambda: self._apply_effect("gate")),
            ("📊 Show analytics", lambda: self.app.island._handle_command("stats")),
            ("🎵 Show chords", lambda: self.app.island._handle_command("chords")),
            ("🎵 Stem separation", lambda: self.app._separate_stems()),
            ("📋 Copy hash", self.app._copy_hash),
            ("↩️ Undo", self.app._undo),
            ("↪️ Redo", self.app._redo),
            ("🎚️ Open EQ", lambda: self.app._open_eq_panel()),
            ("🎚️ Open Mixer", lambda: self.app._open_mixer_panel()),
            ("📈 Analytics Dashboard", lambda: self.app._open_analytics()),
            ("💾 Save preset", lambda: self.app._save_preset_dialog()),
            ("📥 Load preset", lambda: self.app._load_preset_dialog()),
            ("🗑️ Clear history", lambda: self.app._clear_history()),
            ("📊 DB Stats", lambda: self.app._show_db_stats()),
        ]
        self._render_commands(self.all_commands)
        self.bind("<Escape>", lambda e: self.destroy())

    def _render_commands(self, commands):
        for w in self.commands_list.winfo_children():
            w.destroy()
        for name, action in commands:
            btn = ctk.CTkButton(self.commands_list, text=name, height=36, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 12), anchor="w", command=lambda a=action: (a(), self.destroy()))
            btn.pack(fill="x", pady=2)

    def _filter(self, event):
        query = self.search_entry.get().lower()
        filtered = [(n, a) for n, a in self.all_commands if query in n.lower()]
        self._render_commands(filtered)

    def _apply_effect(self, effect):
        if not self.app.current_audio:
            return
        self.app._apply_effect(effect)


# ===== ONBOARDING WIZARD =====
class OnboardingWizard(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Welcome to Aegis Audio Pro")
        self.geometry("600x500")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        self.step = 0
        self.steps = [
            {"title": "🎵 Welcome!", "text": "Aegis Audio Pro is a professional AI music generator with cryptographic licensing.\n\nGenerate royalty-free tracks for games, films, and content."},
            {"title": "⚡ Quick Start", "text": "1. Enter a description of the music you want\n2. Adjust duration and creativity\n3. Click Generate\n4. Get WAV + PDF license instantly"},
            {"title": "🎛️ Effects Studio", "text": "Apply professional effects:\n• Reverb, Delay, Pitch shift\n• 3-band EQ\n• Auto-mastering\n• Stem separation\n• And much more!"},
            {"title": "🔐 Licensing", "text": "Every track comes with a cryptographic license:\n• SHA-256 hash verification\n• Commercial use allowed (PRO)\n• Perpetual, worldwide rights"},
            {"title": "⌨️ Hotkeys", "text": "Ctrl+G - Generate\nCtrl+S - Save project\nCtrl+E - Export\nCtrl+P - Command Palette\nCtrl+Z/Y - Undo/Redo\nSpace - Play/Stop\nF11 - Fullscreen"},
        ]
        self._build_ui()

    def _build_ui(self):
        for w in self.winfo_children():
            w.destroy()
        step = self.steps[self.step]
        ctk.CTkLabel(self, text=step["title"], font=("Segoe UI Variable Display", 28, "bold"), text_color=T["accent"]).pack(pady=(40, 20))
        ctk.CTkLabel(self, text=step["text"], font=("Segoe UI", 14), text_color=T["text_primary"], wraplength=500, justify="left").pack(padx=40, pady=20)
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=40, pady=20)
        if self.step > 0:
            ctk.CTkButton(btn_frame, text="← Back", width=120, height=40, corner_radius=10, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=self._prev).pack(side="left")
        if self.step < len(self.steps) - 1:
            ctk.CTkButton(btn_frame, text="Next →", width=120, height=40, corner_radius=10, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=self._next).pack(side="right")
        else:
            ctk.CTkButton(btn_frame, text="🚀 Get Started", width=150, height=40, corner_radius=10, fg_color=T["success"], hover_color="#2BA84A", text_color="#FFFFFF", command=self._finish).pack(side="right", expand=True)
        dots = ctk.CTkFrame(self, fg_color="transparent")
        dots.pack(pady=(0, 20))
        for i in range(len(self.steps)):
            color = T["accent"] if i == self.step else T["border"]
            ctk.CTkLabel(dots, text="●", font=("Segoe UI", 10), text_color=color).pack(side="left", padx=4)

    def _next(self):
        if self.step < len(self.steps) - 1:
            self.step += 1
            self._build_ui()

    def _prev(self):
        if self.step > 0:
            self.step -= 1
            self._build_ui()

    def _finish(self):
        with open("onboarding_done.txt", "w") as f:
            f.write("done")
        self.destroy()


# ===== EQ PANEL =====
class EQPanel(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("3-Band EQ")
        self.geometry("400x300")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        ctk.CTkLabel(self, text="🎚️ 3-Band Equalizer", font=("Segoe UI Variable Display", 20, "bold"), text_color=T["text_primary"]).pack(pady=(20, 10))
        self.low_var = ctk.DoubleVar(value=0)
        self.mid_var = ctk.DoubleVar(value=0)
        self.high_var = ctk.DoubleVar(value=0)
        for label, var in [("Low (20-300Hz)", self.low_var), ("Mid (300-3kHz)", self.mid_var), ("High (3k+ Hz)", self.high_var)]:
            frame = ctk.CTkFrame(self, fg_color="transparent")
            frame.pack(fill="x", padx=20, pady=8)
            ctk.CTkLabel(frame, text=label, width=150, anchor="w", font=("Segoe UI", 12)).pack(side="left")
            slider = ctk.CTkSlider(frame, from_=-12, to=12, variable=var, command=lambda v, l=label: self._update_label(l, v))
            slider.pack(side="left", fill="x", expand=True, padx=10)
            lbl = ctk.CTkLabel(frame, text="0 dB", width=50, font=("Segoe UI", 11, "bold"), text_color=T["accent"])
            lbl.pack(side="right")
            setattr(self, f"{label.split()[0].lower()}_label", lbl)
        ctk.CTkButton(self, text="Apply EQ", height=40, corner_radius=10, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", font=("Segoe UI", 14, "bold"), command=self._apply).pack(pady=20)
        ctk.CTkButton(self, text="Reset", height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], command=self._reset).pack(pady=(0, 20))

    def _update_label(self, band, value):
        label_name = band.split()[0].lower() + "_label"
        if hasattr(self, label_name):
            getattr(self, label_name).configure(text=f"{float(value):+.1f} dB")

    def _apply(self):
        if not self.app.current_audio:
            return
        self.app._save_undo_state()
        self.app.current_audio = MusicLicenseGenerator.apply_eq_3band(
            self.app.current_audio,
            self.low_var.get(), self.mid_var.get(), self.high_var.get()
        )
        self.app._draw_waveform(self.app.current_audio)
        self.app.set_status("EQ applied")
        self.destroy()

    def _reset(self):
        self.low_var.set(0)
        self.mid_var.set(0)
        self.high_var.set(0)
        for lbl in [self.low_label, self.mid_label, self.high_label]:
            lbl.configure(text="0 dB")


# ===== MIXER PANEL =====
class MixerPanel(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Multi-Track Mixer")
        self.geometry("500x400")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        ctk.CTkLabel(self, text="🎚️ Multi-Track Mixer", font=("Segoe UI Variable Display", 20, "bold"), text_color=T["text_primary"]).pack(pady=(20, 10))
        ctk.CTkLabel(self, text="Layer multiple tracks together", font=("Segoe UI", 12), text_color=T["text_dim"]).pack(pady=(0, 10))
        self.tracks_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", height=250)
        self.tracks_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self.track_entries = []
        self._add_track_row()
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(btn_frame, text="+ Add track", width=120, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=self._add_track_row).pack(side="left")
        ctk.CTkButton(btn_frame, text="🎵 Mix", width=120, height=30, corner_radius=8, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=self._mix).pack(side="right")

    def _add_track_row(self):
        row = ctk.CTkFrame(self.tracks_frame, fg_color=T["card_hover"], corner_radius=8)
        row.pack(fill="x", pady=4)
        file_var = ctk.StringVar()
        vol_var = ctk.DoubleVar(value=1.0)
        ctk.CTkEntry(row, textvariable=file_var, placeholder_text="Select WAV file...", width=250).pack(side="left", padx=8, pady=8)
        ctk.CTkButton(row, text="📂", width=40, height=30, command=lambda v=file_var: self._select_file(v)).pack(side="left", padx=(0, 8))
        ctk.CTkSlider(row, from_=0, to=2, variable=vol_var, width=100).pack(side="left", padx=8)
        ctk.CTkLabel(row, text="Vol", font=("Segoe UI", 10), text_color=T["text_dim"]).pack(side="left", padx=(0, 8))
        self.track_entries.append((file_var, vol_var))

    def _select_file(self, var):
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("WAV", "*.wav")])
        if path:
            var.set(path)

    def _mix(self):
        tracks = []
        volumes = []
        for file_var, vol_var in self.track_entries:
            path = file_var.get()
            if path and os.path.exists(path):
                audio, sr = sf.read(path)
                if sr != SAMPLE_RATE:
                    from scipy.signal import resample
                    audio = resample(audio, int(len(audio) * SAMPLE_RATE / sr))
                tracks.append(audio)
                volumes.append(vol_var.get())
        if not tracks:
            return
        mixed = MusicLicenseGenerator.mix_tracks(tracks, volumes)
        if mixed is not None:
            self.app._save_undo_state()
            self.app.current_audio = mixed
            self.app._draw_waveform(mixed)
            self.app.set_status(f"Mixed {len(tracks)} tracks")
            self.destroy()


# ===== ANALYTICS DASHBOARD =====
class AnalyticsDashboard(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Audio Analytics")
        self.geometry("600x500")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        ctk.CTkLabel(self, text="📊 Audio Analytics Dashboard", font=("Segoe UI Variable Display", 22, "bold"), text_color=T["text_primary"]).pack(pady=(20, 10))
        if not self.app.current_audio:
            ctk.CTkLabel(self, text="Generate a track first", font=("Segoe UI", 14), text_color=T["text_dim"]).pack(pady=40)
            return
        analytics = MusicLicenseGenerator.get_audio_analytics(self.app.current_audio)
        bands = MusicLicenseGenerator.get_frequency_bands(self.app.current_audio)
        bpm = MusicLicenseGenerator.detect_bpm(self.app.current_audio)
        key = MusicLicenseGenerator.detect_key(self.app.current_audio)
        info_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
        info_frame.pack(fill="x", padx=20, pady=10)
        stats = [
            ("Duration", f"{analytics['duration']}s"),
            ("Sample Rate", f"{analytics['sample_rate']} Hz"),
            ("Samples", f"{analytics['samples']:,}"),
            ("RMS", f"{analytics['rms']}"),
            ("Peak", f"{analytics['peak']}"),
            ("Dynamic Range", f"{analytics['dynamic_range_db']} dB"),
            ("BPM", f"{bpm or '--'}"),
            ("Key", f"{key or '--'}"),
        ]
        for i, (label, value) in enumerate(stats):
            row = i // 2
            col = i % 2
            frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            frame.grid(row=row, column=col, padx=10, pady=8, sticky="ew")
            ctk.CTkLabel(frame, text=label, font=("Segoe UI", 11), text_color=T["text_dim"]).pack(anchor="w")
            ctk.CTkLabel(frame, text=value, font=("Segoe UI", 14, "bold"), text_color=T["accent"]).pack(anchor="w")
        if bands:
            bands_frame = ctk.CTkFrame(self, fg_color=T["card_hover"], corner_radius=12)
            bands_frame.pack(fill="x", padx=20, pady=10)
            ctk.CTkLabel(bands_frame, text="Frequency Bands", font=("Segoe UI", 13, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=15, pady=(10, 5))
            for band, val in bands.items():
                row = ctk.CTkFrame(bands_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=4)
                ctk.CTkLabel(row, text=band, width=150, anchor="w", font=("Segoe UI", 11)).pack(side="left")
                bar_width = min(300, val * 100)
                bar = ctk.CTkFrame(row, fg_color=T["accent"], height=12, width=bar_width, corner_radius=6)
                bar.pack(side="left", padx=10)
                ctk.CTkLabel(row, text=f"{val:.2f}", width=60, font=("Segoe UI", 11), text_color=T["text_dim"]).pack(side="right")


# ===== PRESET MANAGER =====
class PresetManager(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Preset Manager")
        self.geometry("500x400")
        self.configure(fg_color=T["card"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(app)
        ctk.CTkLabel(self, text="💾 Preset Manager", font=("Segoe UI Variable Display", 22, "bold"), text_color=T["text_primary"]).pack(pady=(20, 10))
        self.name_entry = ctk.CTkEntry(self, placeholder_text="Preset name...", height=40, font=("Segoe UI", 14))
        self.name_entry.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(self, text="💾 Save Current Settings", height=40, corner_radius=10, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=self._save).pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(self, text="Saved Presets:", font=("Segoe UI", 13, "bold"), text_color=T["text_secondary"]).pack(anchor="w", padx=20, pady=(20, 10))
        self.presets_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", height=200)
        self.presets_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self._load_presets()

    def _load_presets(self):
        for w in self.presets_frame.winfo_children():
            w.destroy()
        presets = self.app.db.get_presets()
        if not presets:
            ctk.CTkLabel(self.presets_frame, text="No presets saved", font=("Segoe UI", 12), text_color=T["text_dim"]).pack(pady=20)
            return
        for p in presets:
            row = ctk.CTkFrame(self.presets_frame, fg_color=T["card_hover"], corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=p[1], font=("Segoe UI", 12), text_color=T["text_primary"]).pack(side="left", padx=10, pady=8)
            ctk.CTkButton(row, text="Load", width=70, height=28, corner_radius=6, fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=lambda n=p[1]: self._load(n)).pack(side="right", padx=4)
            ctk.CTkButton(row, text="Delete", width=70, height=28, corner_radius=6, fg_color=T["danger"], hover_color="#CC2936", text_color="#FFFFFF", command=lambda n=p[1]: self._delete(n)).pack(side="right", padx=4)

    def _save(self):
        name = self.name_entry.get().strip()
        if not name:
            return
        settings = {
            "prompt": self.app.prompt_box.get("1.0", "end").strip(),
            "duration": self.app.duration_slider.get(),
            "temperature": self.app.temp_slider.get(),
            "guidance_scale": self.app.guidance_slider.get(),
            "loop_mode": self.app.loop_var.get(),
            "batch_count": self.app.batch_var.get(),
        }
        self.app.db.save_preset(name, settings)
        self.app.set_status(f"Preset saved: {name}")
        self.name_entry.delete(0, "end")
        self._load_presets()

    def _load(self, name):
        settings = self.app.db.load_preset(name)
        if settings:
            self.app._set_prompt(settings.get("prompt", ""))
            self.app.duration_slider.set(settings.get("duration", 10))
            self.app.temp_slider.set(settings.get("temperature", 1.0))
            self.app.guidance_slider.set(settings.get("guidance_scale", 3.0))
            self.app.loop_var.set(settings.get("loop_mode", False))
            self.app.batch_var.set(settings.get("batch_count", 1))
            self.app.set_status(f"Preset loaded: {name}")
            self.destroy()

    def _delete(self, name):
        self.app.db.delete_preset(name)
        self.app.set_status(f"Preset deleted: {name}")
        self._load_presets()


# ===== MAIN APP =====
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

TRANSLATIONS = {
    "ru": {"generate": "⚡ Сгенерировать (Ctrl+G)", "export": "📤 Экспорт (Ctrl+E)", "save": "💾 Сохранить (Ctrl+S)", "play": "▶ Play (Space)", "stop": "⏸ Стоп (Space)", "folder": "📂 Папка", "description": "ОПИСАНИЕ", "random": "Случайный", "duration": "Длительность", "creativity": "Креативность", "accuracy": "Точность промпта", "licensee": "Лицензиат", "fixed_seed": "Фикс. seed", "loop_mode": "🔄 Loop Mode", "batch": "Вариантов:", "result": "РЕЗУЛЬТАТ", "metadata": "МЕТАДАННЫЕ ТРЕКА", "history": "История", "effects": "🎛️ AUDIO EFFECTS", "theme": "🎨 Тема", "lang": "🌐 Язык", "commands": "⌨️ Команды (Ctrl+P)", "favorites": "⭐ Избранное", "search": "🔍 Поиск..."},
    "en": {"generate": "⚡ Generate (Ctrl+G)", "export": "📤 Export (Ctrl+E)", "save": "💾 Save (Ctrl+S)", "play": "▶ Play (Space)", "stop": "⏸ Stop (Space)", "folder": "📂 Folder", "description": "DESCRIPTION", "random": "Random", "duration": "Duration", "creativity": "Creativity", "accuracy": "Prompt Accuracy", "licensee": "Licensee", "fixed_seed": "Fixed seed", "loop_mode": "🔄 Loop Mode", "batch": "Variants:", "result": "RESULT", "metadata": "TRACK METADATA", "history": "History", "effects": "🎛️ AUDIO EFFECTS", "theme": "🎨 Theme", "lang": "🌐 Language", "commands": "⌨️ Commands (Ctrl+P)", "favorites": "⭐ Favorites", "search": "🔍 Search..."},
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aegis Audio Pro")
        self.geometry("1200x1000")
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
        self.favorites = []
        self._pulse_state = False
        self._wave_fig = None
        self._wave_ax = None
        self._wave_canvas = None
        self._view_mode = "waveform"
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
        self.after(1000, self._check_onboarding)
        threading.Thread(target=self._load_model, daemon=True).start()

    def _check_onboarding(self):
        if not os.path.exists("onboarding_done.txt"):
            OnboardingWizard(self)

    def _bind_hotkeys(self):
        self.bind("<Control-g>", lambda e: self._on_generate())
        self.bind("<Control-s>", lambda e: self._save_project())
        self.bind("<Control-e>", lambda e: self._export_audio())
        self.bind("<Control-p>", lambda e: self._open_command_palette())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<space>", lambda e: self._toggle_play())
        self.bind("<F11>", lambda e: self._toggle_fullscreen())

    def _build_ui(self):
        self.island = DynamicIsland(self, self)
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=24)
        left = ctk.CTkFrame(main, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        right = ctk.CTkFrame(main, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1, width=340)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)
        # HEADER
        header = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        header.pack(fill="x", pady=(0, 14))
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=22, pady=(18, 6))
        ctk.CTkLabel(title_row, text="Aegis Audio Pro", font=("Segoe UI Variable Display", 30, "bold"), text_color=T["text_primary"]).pack(side="left")
        self.license_label = ctk.CTkLabel(title_row, text=f"[{LICENSE_MODE}]", font=("Segoe UI", 12, "bold"), text_color=T["success"] if LICENSE_MODE == "PRO" else T["warning"])
        self.license_label.pack(side="right", padx=(0, 10))
        self.fs_btn = ctk.CTkButton(title_row, text="⛶", width=40, height=30, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 14), command=self._toggle_fullscreen)
        self.fs_btn.pack(side="right", padx=(0, 10))
        self.counter_label = ctk.CTkLabel(title_row, text="0 tracks", font=("Segoe UI", 12), text_color=T["text_dim"])
        self.counter_label.pack(side="right", pady=6)
        ctk.CTkLabel(header, text="Royalty-free AI audio with cryptographic licensing", font=("Segoe UI", 13), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(0, 18))
        # STATUS + PROGRESS
        status_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        status_card.pack(fill="x", pady=(0, 14))
        self.status_label = ctk.CTkLabel(status_card, text="Initializing...", font=("Consolas", 12), text_color=T["warning"], anchor="w")
        self.status_label.pack(fill="x", padx=22, pady=(14, 8))
        self.progress_bar = ctk.CTkProgressBar(status_card, height=6, corner_radius=3, progress_color=T["accent"], fg_color=T["border"])
        self.progress_bar.pack(fill="x", padx=22, pady=(0, 14))
        self.progress_bar.set(0)
        # PROMPT
        prompt_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        prompt_card.pack(fill="x", pady=(0, 14))
        prompt_header = ctk.CTkFrame(prompt_card, fg_color="transparent")
        prompt_header.pack(fill="x", padx=22, pady=(16, 8))
        ctk.CTkLabel(prompt_header, text=TRANSLATIONS[CURRENT_LANG]["description"], font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(side="left")
        ctk.CTkButton(prompt_header, text=TRANSLATIONS[CURRENT_LANG]["random"], width=110, height=28, corner_radius=14, font=("Segoe UI", 11), fg_color=T["accent_light"], hover_color=T["accent_hover"], text_color=T["accent"], command=self._random_prompt).pack(side="right")
        self.prompt_box = ctk.CTkTextbox(prompt_card, height=92, corner_radius=14, font=("Segoe UI", 13), wrap="word", fg_color=T["card_hover"], border_color=T["border"], border_width=1)
        self.prompt_box.pack(fill="x", padx=22, pady=(0, 10))
        self.prompt_box.insert("1.0", PRESETS["Trap"]["prompt"])
        chips_frame = ctk.CTkFrame(prompt_card, fg_color="transparent")
        chips_frame.pack(fill="x", padx=22, pady=(0, 18))
        for name, data in PRESETS.items():
            ctk.CTkButton(chips_frame, text=name, width=100, height=30, corner_radius=15, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], font=("Segoe UI", 11), command=lambda t=data["prompt"]: self._set_prompt(t)).pack(side="left", padx=(0, 6))
        # SETTINGS
        settings_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        settings_card.pack(fill="x", pady=(0, 14))
        self._add_slider_row(settings_card, TRANSLATIONS[CURRENT_LANG]["duration"], 5, 120, 10, self._update_duration_label)
        self.duration_slider = settings_card._last_slider
        self.duration_label = settings_card._last_value_label
        self._add_slider_row(settings_card, TRANSLATIONS[CURRENT_LANG]["creativity"], 0.5, 2.0, 1.0, self._update_temp_label)
        self.temp_slider = settings_card._last_slider
        self.temp_label = settings_card._last_value_label
        self._add_slider_row(settings_card, TRANSLATIONS[CURRENT_LANG]["accuracy"], 1.0, 10.0, 3.0, self._update_guidance_label)
        self.guidance_slider = settings_card._last_slider
        self.guidance_label = settings_card._last_value_label
        loop_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        loop_row.pack(fill="x", padx=22, pady=(0, 10))
        ctk.CTkCheckBox(loop_row, text=TRANSLATIONS[CURRENT_LANG]["loop_mode"], variable=self.loop_var, font=("Segoe UI", 11), fg_color=T["accent"], hover_color=T["accent_hover"], checkmark_color="#FFFFFF", border_color=T["border"]).pack(side="left")
        batch_row = ctk.CTkFrame(settings_card, fg_color="transparent")
        batch_row.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkLabel(batch_row, text=TRANSLATIONS[CURRENT_LANG]["batch"], font=("Segoe UI", 12)).pack(side="left")
        for opt in [1, 3, 5]:
            ctk.CTkRadioButton(batch_row, text=str(opt), variable=self.batch_var, value=opt, font=("Segoe UI", 11), fg_color=T["accent"], text_color=T["text_primary"]).pack(side="left", padx=10)
        row = ctk.CTkFrame(settings_card, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkLabel(row, text=TRANSLATIONS[CURRENT_LANG]["licensee"], font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(row, width=200, placeholder_text="User", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10)
        self.user_entry.pack(side="left", padx=12)
        ctk.CTkCheckBox(row, text=TRANSLATIONS[CURRENT_LANG]["fixed_seed"], variable=self.seed_var, font=("Segoe UI", 11), fg_color=T["accent"], hover_color=T["accent_hover"], checkmark_color="#FFFFFF", border_color=T["border"]).pack(side="left", padx=(20, 0))
        self.seed_var.trace("w", lambda *a: self._toggle_seed())
        self.seed_entry = ctk.CTkEntry(row, width=90, placeholder_text="42", fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10, state="disabled")
        self.seed_entry.pack(side="left", padx=10)
        # ACTION BUTTONS
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 14))
        self.generate_btn = ctk.CTkButton(btn_frame, text=TRANSLATIONS[CURRENT_LANG]["generate"], height=58, corner_radius=18, font=("Segoe UI Variable Display", 17, "bold"), fg_color=T["accent"], hover_color=T["accent_hover"], text_color="#FFFFFF", command=self._on_generate)
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.export_btn = ctk.CTkButton(btn_frame, text=TRANSLATIONS[CURRENT_LANG]["export"], height=58, corner_radius=18, font=("Segoe UI", 14, "bold"), fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], command=self._export_audio, state="disabled")
        self.export_btn.pack(side="left", fill="x", expand=True)
        # WAVEFORM / SPECTRUM
        self.wave_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1, height=150)
        self.wave_card.pack(fill="x", pady=(0, 14))
        self.wave_card.pack_propagate(False)
        wave_header = ctk.CTkFrame(self.wave_card, fg_color="transparent")
        wave_header.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(wave_header, text="VISUALIZATION", font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(side="left")
        self.view_btn = ctk.CTkButton(wave_header, text="📊 Spectrum", width=110, height=26, corner_radius=10, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_secondary"], font=("Segoe UI", 10), command=self._toggle_view)
        self.view_btn.pack(side="right")
        self.wave_placeholder = ctk.CTkLabel(self.wave_card, text="Visualization will appear after generation", font=("Segoe UI", 12), text_color=T["text_dim"])
        self.wave_placeholder.pack(expand=True)
        # AUDIO EFFECTS STUDIO
        effects_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        effects_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(effects_card, text=TRANSLATIONS[CURRENT_LANG]["effects"], font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(16, 8))
        effects_grid = ctk.CTkFrame(effects_card, fg_color="transparent")
        effects_grid.pack(fill="x", padx=22, pady=(0, 16))
        effect_buttons = [
            ("🔊 Reverb", "reverb"), ("🔁 Delay", "delay"), ("🎵 Pitch +2", "pitch_up"),
            ("🎵 Pitch -2", "pitch_down"), ("⏩ Speed 1.2x", "speed_up"), ("⏪ Reverse", "reverse"),
            ("🔉 Bass Boost", "bass"), ("📏 Normalize", "normalize"), ("🎚️ Auto Master", "master"),
            ("🎛️ Harmonizer", "harmonizer"), ("🔇 Spectral Gate", "gate"), ("🆚 A/B Compare", "ab"),
            ("↩️ Undo", "undo"), ("↪️ Redo", "redo"), ("📋 Copy Hash", "copy_hash"),
            ("🎵 Stems", "stems"), ("🎚️ EQ Panel", "eq_panel"), ("🎚️ Mixer", "mixer"),
        ]
        for i, (text, cmd) in enumerate(effect_buttons):
            row_idx = i // 6
            col_idx = i % 6
            btn = ctk.CTkButton(effects_grid, text=text, width=120, height=36, corner_radius=10, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 10), command=lambda c=cmd: self._handle_effect(c))
            btn.grid(row=row_idx, column=col_idx, padx=4, pady=4, sticky="ew")
        for c in range(6):
            effects_grid.grid_columnconfigure(c, weight=1)
        # METADATA
        meta_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        meta_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(meta_card, text=TRANSLATIONS[CURRENT_LANG]["metadata"], font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(16, 8))
        self.meta_text = ctk.CTkLabel(meta_card, text="BPM: -- | Key: -- | Duration: -- | RMS: --", font=("Consolas", 11), text_color=T["text_dim"], wraplength=700, justify="left")
        self.meta_text.pack(anchor="w", padx=22, pady=(0, 16))
        # RESULT
        result_card = ctk.CTkFrame(left, fg_color=T["card"], corner_radius=22, border_color=T["border"], border_width=1)
        result_card.pack(fill="x")
        ctk.CTkLabel(result_card, text=TRANSLATIONS[CURRENT_LANG]["result"], font=("Segoe UI", 11, "bold"), text_color=T["text_dim"]).pack(anchor="w", padx=22, pady=(16, 8))
        self.result_text = ctk.CTkLabel(result_card, text="Empty. Click Generate.", font=("Consolas", 11), text_color=T["text_dim"], wraplength=700, justify="left")
        self.result_text.pack(anchor="w", padx=22, pady=(0, 10))
        btn_row = ctk.CTkFrame(result_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, pady=(0, 18))
        self.play_btn = ctk.CTkButton(btn_row, text=TRANSLATIONS[CURRENT_LANG]["play"], width=130, height=36, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 12), command=self._toggle_play, state="disabled")
        self.play_btn.pack(side="left", padx=(0, 8))
        self.save_btn = ctk.CTkButton(btn_row, text=TRANSLATIONS[CURRENT_LANG]["save"], width=160, height=36, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 12), command=self._save_project, state="disabled")
        self.save_btn.pack(side="left", padx=(0, 8))
        self.open_btn = ctk.CTkButton(btn_row, text=TRANSLATIONS[CURRENT_LANG]["folder"], width=100, height=36, corner_radius=12, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["accent"], font=("Segoe UI", 12), command=self._open_folder, state="disabled")
        self.open_btn.pack(side="left")
        # RIGHT PANEL
        ctk.CTkLabel(right, text=TRANSLATIONS[CURRENT_LANG]["history"], font=("Segoe UI Variable Display", 18, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=20, pady=(20, 14))
        self.search_entry = ctk.CTkEntry(right, placeholder_text=TRANSLATIONS[CURRENT_LANG]["search"], fg_color=T["card_hover"], border_color=T["border"], border_width=1, corner_radius=10, textvariable=self.search_var)
        self.search_entry.pack(fill="x", padx=12, pady=(0, 10))
        self.search_var.trace("w", lambda *a: self._update_history())
        # Quick actions
        quick_frame = ctk.CTkFrame(right, fg_color="transparent")
        quick_frame.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(quick_frame, text="💾 Presets", width=140, height=32, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 11), command=lambda: PresetManager(self)).pack(side="left", padx=(0, 4))
        ctk.CTkButton(quick_frame, text="📊 Analytics", width=140, height=32, corner_radius=8, fg_color=T["card_hover"], hover_color=T["border"], text_color=T["text_primary"], font=("Segoe UI", 11), command=lambda: AnalyticsDashboard(self)).pack(side="right", padx=(4, 0))
        ctk.CTkLabel(right, text=TRANSLATIONS[CURRENT_LANG]["favorites"], font=("Segoe UI", 12, "bold"), text_color=T["warning"]).pack(anchor="w", padx=20, pady=(10, 6))
        self.favorites_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent", height=120, scrollbar_button_color=T["border"], scrollbar_button_hover_color=T["card_hover"])
        self.favorites_scroll.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(right, text="All", font=("Segoe UI", 12, "bold"), text_color=T["text_primary"]).pack(anchor="w", padx=20, pady=(10, 6))
        self.history_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent", scrollbar_button_color=T["border"], scrollbar_button_hover_color=T["card_hover"])
        self.history_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 14))
        self.history_empty = ctk.CTkLabel(self.history_scroll, text="Tracks will appear\nhere", font=("Segoe UI", 12), text_color=T["text_dim"], justify="center")
        self.history_empty.pack(expand=True, pady=40)

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
        elif cmd == "eq_panel":
            self._open_eq_panel()
        elif cmd == "mixer":
            self._open_mixer_panel()
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

    def _toggle_theme(self):
        global CURRENT_THEME, T
        themes_list = list(THEMES.keys())
        idx = themes_list.index(CURRENT_THEME)
        CURRENT_THEME = themes_list[(idx + 1) % len(themes_list)]
        T = THEMES[CURRENT_THEME]
        ctk.set_appearance_mode(CURRENT_THEME)
        self.configure(fg_color=T["app"])
        self.set_status(f"Theme: {CURRENT_THEME}")

    def _toggle_language(self):
        global CURRENT_LANG
        CURRENT_LANG = "en" if CURRENT_LANG == "ru" else "ru"
        self.set_status(f"Language: {CURRENT_LANG.upper()}")

    def _toggle_view(self):
        self._view_mode = "spectrum" if self._view_mode == "waveform" else "waveform"
        self.view_btn.configure(text="🌊 Waveform" if self._view_mode == "spectrum" else "📊 Spectrum")
        if self.current_audio is not None:
            self._draw_waveform(self.current_audio)

    def _open_command_palette(self):
        CommandPalette(self)

    def _open_eq_panel(self):
        if not self.current_audio:
            self.set_status("Generate a track first")
            return
        EQPanel(self)

    def _open_mixer_panel(self):
        MixerPanel(self)

    def _open_analytics(self):
        AnalyticsDashboard(self)

    def _save_preset_dialog(self):
        PresetManager(self)

    def _load_preset_dialog(self):
        PresetManager(self)

    def _clear_history(self):
        self.history.clear()
        self._update_history()
        self.set_status("History cleared")

    def _show_db_stats(self):
        stats = self.db.get_stats()
        self.set_status(f"DB: {stats['total']} tracks, {stats['favorites']} favorites")

    def _add_slider_row(self, parent, label, from_, to, default, update_fn):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(14, 6))
        ctk.CTkLabel(row, text=label, font=("Segoe UI", 12), text_color=T["text_secondary"]).pack(side="left")
        slider = ctk.CTkSlider(row, from_=from_, to=to, width=280, command=update_fn, progress_color=T["accent"], fg_color=T["border"], button_color=T["text_primary"], button_hover_color=T["card_hover"], button_length=24)
        slider.set(default)
        slider.pack(side="left", padx=14)
        value_label = ctk.CTkLabel(row, text="", font=("Segoe UI", 12, "bold"), text_color=T["accent"])
        value_label.pack(side="left")
        parent._last_slider = slider
        parent._last_value_label = value_label

    def _pulse_status(self):
        if self.model_loaded:
            return
        self._pulse_state = not self._pulse_state
        color = T["accent"] if self._pulse_state else T["warning"]
        current = self.status_label.cget("text")
        if "Init" in current or "Load" in current or "Инициализация" in current or "Загрузка" in current:
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
            self.seed_entry.delete(0, "end")
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

    def get_uptime(self):
        delta = datetime.now() - self.start_time
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} min"

    def _load_model(self):
        try:
            self.generator.load()
            self.model_loaded = True
            self.after(0, lambda: self.set_status("Ready"))
            self.after(0, lambda: self.set_progress(100))
            self.after(0, lambda: self.status_label.configure(text_color=T["success"]))
        except Exception as e:
            self.after(0, lambda: self.set_status(f"Error: {e}"))
            self.after(0, lambda: self.status_label.configure(text_color=T["danger"]))

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
            self.set_status("Undo")

    def _redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.current_audio.copy() if self.current_audio is not None else None)
            self.current_audio = self.redo_stack.pop()
            self._draw_waveform(self.current_audio)
            self.set_status("Redo")

    def _apply_effect(self, effect):
        if self.current_audio is None:
            self.set_status("Generate a track first")
            return
        self._save_undo_state()
        try:
            if effect == "reverb":
                self.current_audio = MusicLicenseGenerator.apply_reverb(self.current_audio)
            elif effect == "delay":
                self.current_audio = MusicLicenseGenerator.apply_delay(self.current_audio)
            elif effect == "pitch_up":
                self.current_audio = MusicLicenseGenerator.apply_pitch_shift(self.current_audio, 2)
            elif effect == "pitch_down":
                self.current_audio = MusicLicenseGenerator.apply_pitch_shift(self.current_audio, -2)
            elif effect == "speed_up":
                self.current_audio = MusicLicenseGenerator.apply_speed_change(self.current_audio, 1.2)
            elif effect == "reverse":
                self.current_audio = MusicLicenseGenerator.apply_reverse(self.current_audio)
            elif effect == "bass":
                self.current_audio = MusicLicenseGenerator.apply_bass_boost(self.current_audio)
            elif effect == "normalize":
                self.current_audio = MusicLicenseGenerator.apply_normalize(self.current_audio)
            elif effect == "master":
                self.current_audio = MusicLicenseGenerator.apply_auto_master(self.current_audio)
            elif effect == "harmonizer":
                self.current_audio = MusicLicenseGenerator.apply_harmonizer(self.current_audio)
            elif effect == "gate":
                self.current_audio = MusicLicenseGenerator.apply_spectral_gate(self.current_audio)
            self._draw_waveform(self.current_audio)
            self.set_status(f"Applied: {effect}")
        except Exception as e:
            self.set_status(f"Effect error: {e}")

    def _separate_stems(self):
        if not self.current_audio:
            self.set_status("Generate a track first")
            return
        self._save_undo_state()
        stems = MusicLicenseGenerator.separate_stems_simple(self.current_audio)
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
            sd.play(self.original_audio, SAMPLE_RATE)
            time.sleep(len(self.original_audio) / SAMPLE_RATE)
            sd.play(self.current_audio, SAMPLE_RATE)
            time.sleep(len(self.current_audio) / SAMPLE_RATE)
            self.is_playing = False
            self.after(0, lambda: self.play_btn.configure(text=TRANSLATIONS[CURRENT_LANG]["play"]))
        threading.Thread(target=play_alternating, daemon=True).start()
        self.play_btn.configure(text="🆚 A/B Playing...")
        self.set_status("A/B Compare: Original → Current")

    def _copy_hash(self):
        if not self.current_audio_path:
            self.set_status("Generate a track first")
            return
        file_hash = MusicLicenseGenerator.calculate_hash(self.current_audio_path)
        pyperclip.copy(file_hash)
        self.set_status(f"Hash copied: {file_hash[:16]}...")

    def _on_generate(self):
        if not self.model_loaded:
            self.set_status("Model still loading...")
            return
        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            self.set_status("Enter description")
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
                self.set_status("Seed must be number")
                return
        self.generate_btn.configure(state="disabled", text="Generating...")
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.set_progress(0)
        self.status_label.configure(text_color=T["accent"])
        threading.Thread(target=self._generate_worker, args=(prompt, duration, user_name, seed, temperature, guidance_scale, loop_mode, batch_count), daemon=True).start()

    def _generate_worker(self, prompt, duration, user_name, seed, temperature, guidance_scale, loop_mode, batch_count):
        try:
            best_audio = None
            best_score = -1
            for i in range(batch_count):
                self.status(f"Generating variant {i+1}/{batch_count}...")
                audio = self.generator.generate(prompt, duration, seed + i if seed else None, temperature, guidance_scale, loop_mode)
                score = np.std(audio)
                if score > best_score:
                    best_score = score
                    best_audio = audio
                self.progress(int((i + 1) / batch_count * 90))
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
            info = (f"File: {zip_file}\nDuration: {dur_str}\nLicensee: {user_name}\nLicense: {license_type}\nBPM: {bpm or '--'} | Key: {key or '--'}\nRMS: {analytics['rms']} | Peak: {analytics['peak']}\nDynamic Range: {analytics['dynamic_range_db']} dB\nTemp: {temperature:.1f} | Guidance: {guidance_scale:.1f}\nSHA-256: {file_hash[:32]}...\nSize: {os.path.getsize(zip_file) // 1024} KB")
            if seed is not None:
                info += f"\nSeed: {seed}"
            if batch_count > 1:
                info += f"\nVariants generated: {batch_count}"
            track_id = self.db.add_track(
                prompt=prompt, duration=duration, bpm=bpm, key=key,
                rms=analytics['rms'], peak=analytics['peak'],
                dynamic_range=analytics['dynamic_range_db'],
                license_type=license_type, licensee=user_name,
                file_hash=file_hash, file_path=zip_file,
                seed=seed, temperature=temperature, guidance_scale=guidance_scale,
                loop_mode=1 if loop_mode else 0
            )
            self.history.insert(0, {"id": track_id, "time": datetime.now().strftime("%H:%M"), "prompt": prompt[:60] + "..." if len(prompt) > 60 else prompt, "duration": dur_str, "file": zip_file, "bpm": bpm, "hash": file_hash, "favorite": False})
            self.history = self.history[:20]
            def done():
                self.result_text.configure(text=info, text_color=T["text_primary"])
                self.meta_text.configure(text=f"BPM: {bpm or '--'} | Key: {key or '--'} | Duration: {dur_str} | RMS: {analytics['rms']} | Loop: {'Yes' if loop_mode else 'No'}", text_color=T["text_primary"])
                self.generate_btn.configure(state="normal", text=TRANSLATIONS[CURRENT_LANG]["generate"])
                self.play_btn.configure(state="normal")
                self.save_btn.configure(state="normal")
                self.export_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.counter_label.configure(text=f"{self.track_count} tracks")
                self.set_status("Done")
                self.status_label.configure(text_color=T["success"])
                self.set_progress(100)
                self._update_history()
                self._update_favorites()
                self._draw_waveform(best_audio)
                self._notify("Track ready!", f"{dur_str} | {bpm or '--'} BPM")
            self.after(0, done)
        except Exception as e:
            def err():
                self.generate_btn.configure(state="normal", text=TRANSLATIONS[CURRENT_LANG]["generate"])
                self.set_status(f"Error: {e}")
                self.status_label.configure(text_color=T["danger"])
                print(traceback.format_exc())
            self.after(0, err)

    def _notify(self, title, message):
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=3, icon_path=None)
        except:
            pass

    def _save_project(self):
        if not self.current_audio:
            self.set_status("No track to save")
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
            "timestamp": datetime.now().isoformat(),
        }
        filename = f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(project, f, indent=2, ensure_ascii=False)
        self.set_status(f"Project saved: {filename}")

    def _export_audio(self):
        if not self.current_audio:
            self.set_status("No track to export")
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
                self.set_status(f"Exported: {export_path}")
            except Exception as e:
                self.set_status(f"Export error: {e}")

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
            ctk.CTkLabel(self.favorites_scroll, text="No favorites yet", font=("Segoe UI", 11), text_color=T["text_dim"]).pack(pady=10)
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
        for w in self.wave_card.winfo_children():
            if isinstance(w, ctk.CTkFrame) and w != self.wave_card:
                continue
            if hasattr(w, 'winfo_name') and 'header' not in str(w):
                try:
                    w.destroy()
                except:
                    pass
        for w in self.wave_card.winfo_children():
            if w != self.wave_placeholder and not isinstance(w, ctk.CTkFrame):
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
            self.play_btn.configure(text=TRANSLATIONS[CURRENT_LANG]["play"])
        else:
            sd.play(self.current_audio, SAMPLE_RATE)
            self.is_playing = True
            self.play_btn.configure(text=TRANSLATIONS[CURRENT_LANG]["stop"])

    def _open_folder(self):
        os.startfile(script_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()
