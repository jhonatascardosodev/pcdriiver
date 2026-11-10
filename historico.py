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
    with closing(_con()) as c, c:
        c.execute("INSERT OR REPLACE INTO amostras VALUES (?,?,?,?)",
                  (int(time.time()), cpu, ram, json.dumps(_top_procs())))


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
                gravar(cpu, ram)
                self._checar(cpu, ram)
                n += 1
                if n % 360 == 0:
                    limpar_antigos()
            except Exception:
                pass

    def _checar(self, cpu, ram):
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
