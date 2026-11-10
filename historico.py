"""Coleta e guarda o histórico de CPU/RAM + quem mais consumia (SQLite)."""
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing

import psutil

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historico.db")


def _con():
    return sqlite3.connect(DB, timeout=10)


def iniciar():
    with closing(_con()) as c, c:
        c.execute("CREATE TABLE IF NOT EXISTS amostras "
                  "(ts INTEGER PRIMARY KEY, cpu REAL, ram REAL, top TEXT)")


def _top_procs(n=3):
    ram = defaultdict(int)
    cpu = defaultdict(float)
    for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
        try:
            nome = p.info["name"] or "?"
            if nome == "System Idle Process":
                continue
            ram[nome] += p.info["memory_info"].rss
            cpu[nome] += p.info["cpu_percent"] or 0
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
    nc = psutil.cpu_count() or 1
    top_ram = sorted(ram.items(), key=lambda kv: kv[1], reverse=True)[:n]
    top_cpu = sorted(cpu.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return {
        "ram": [[k, round(v / 1024**2)] for k, v in top_ram],
        "cpu": [[k, round(v / nc, 1)] for k, v in top_cpu],
    }


def gravar(cpu, ram):
    top = _top_procs()
    with closing(_con()) as c, c:
        c.execute("INSERT OR REPLACE INTO amostras VALUES (?,?,?,?)",
                  (int(time.time()), cpu, ram, json.dumps(top)))
    return top


def ler_sensores():
    """Lê o servidor web da LibreHardwareMonitor (http://localhost:8085/data.json).
    Devolve [(hardware, sensor, grupo, texto, valor)] de temperaturas e ventoinhas;
    lista vazia se ela não estiver aberta."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8085/data.json", timeout=2) as r:
            raiz = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []
    achados = []
    grupos = {"Temperatures": "Temperatura", "Fans": "Ventoinha"}

    def andar(no, hardware):
        filhos = no.get("Children", [])
        grupo = grupos.get(no.get("Text"))
        if grupo:
            for f in filhos:
                texto = f.get("Value", "")
                if not texto:
                    continue
                try:
                    valor = float(texto.split()[0].replace(",", "."))
                except (ValueError, IndexError):
                    valor = None
                achados.append((hardware, f.get("Text", ""), grupo, texto, valor))
            return
        for f in filhos:
            andar(f, no.get("Text", "") if f.get("Children") else hardware)

    andar(raiz, "")
    return achados


def ler_temperaturas():
    """[(hardware, sensor, graus)] só de temperaturas."""
    return [(h, s, v) for h, s, g, _, v in ler_sensores() if g == "Temperatura" and v is not None]


def limpar_antigos(dias=7):
    with closing(_con()) as c, c:
        c.execute("DELETE FROM amostras WHERE ts < ?", (int(time.time()) - dias * 86400,))


def consultar(segundos):
    with closing(_con()) as c:
        cur = c.execute("SELECT ts, cpu, ram, top FROM amostras WHERE ts >= ? ORDER BY ts",
                        (int(time.time()) - segundos,))
        return cur.fetchall()


class Coletor(threading.Thread):
    """Grava uma amostra a cada `intervalo` segundos e dispara alertas."""

    def __init__(self, on_alert, intervalo=10):
        super().__init__(daemon=True)
        self.on_alert = on_alert
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._ultimo_alerta = {}
        self._cpu_alta = 0

    def parar(self):
        self._parar.set()

    def _alertar(self, chave, titulo, msg, espera=600):
        agora = time.time()
        if agora - self._ultimo_alerta.get(chave, 0) >= espera:
            self._ultimo_alerta[chave] = agora
            try:
                self.on_alert(titulo, msg)
            except Exception:
                pass

    def run(self):
        try:
            iniciar()
        except Exception:
            return
        n = 0
        while not self._parar.wait(self.intervalo):
            try:
                cpu = psutil.cpu_percent(interval=1)
                ram = psutil.virtual_memory().percent
                top = gravar(cpu, ram)
                self._checar(cpu, ram, top)
                if n % 3 == 0:  # temperaturas a cada ~30 s
                    self._checar_temps()
                n += 1
                if n % 360 == 0:
                    limpar_antigos()
            except Exception:
                pass

    # limites de alerta (°C e MB)
    LIMITES = {"cpu": 85, "gpu": 85, "disco": 60, "proc_mb": 4096}

    def _checar_temps(self):
        for hw, sensor, graus in ler_temperaturas():
            if sensor == "CPU Package" and graus >= self.LIMITES["cpu"]:
                self._alertar("t_cpu", "CPU quente", f"CPU a {graus:.0f} °C.", espera=300)
            elif sensor == "GPU Core" and graus >= self.LIMITES["gpu"]:
                self._alertar("t_gpu", "GPU quente", f"GPU a {graus:.0f} °C.", espera=300)
            elif sensor == "Temperature" and graus >= self.LIMITES["disco"]:
                self._alertar("t_" + hw, "Disco quente", f"{hw.strip()} a {graus:.0f} °C.", espera=1800)

    def _checar(self, cpu, ram, top=None):
        for nome, mb in (top or {}).get("ram", []):
            if mb >= self.LIMITES["proc_mb"]:
                self._alertar("p_" + nome, "Programa usando muita RAM",
                              f"{nome} está usando {mb / 1024:.1f} GB de RAM.", espera=3600)
        self._cpu_alta = self._cpu_alta + 1 if cpu > 90 else 0
        if self._cpu_alta >= 3:
            self._alertar("cpu", "CPU alta", f"CPU em {cpu:.0f}% há alguns segundos.")
        if ram > 90:
            self._alertar("ram", "RAM quase cheia", f"RAM em {ram:.0f}%. Feche programas pesados.")
        try:
            livre = psutil.disk_usage("C:\\").free
            if livre < 5 * 1024**3:
                self._alertar("disco", "C: quase cheio",
                              f"Só {livre / 1024**3:.1f} GB livres no C:.", espera=3600)
        except OSError:
            pass
