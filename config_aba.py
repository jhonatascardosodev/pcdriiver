"""Aba Configurações: limites dos alertas e início automático com o Windows."""
import tkinter as tk
from tkinter import messagebox, ttk

import caminhos
import historico
import ui

try:
    import winreg
except ImportError:  # fora do Windows
    winreg = None

CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME_RUN = "MonitorPC"

# (chave em historico.LIMITES, rótulo, unidade, mínimo, máximo, fator de exibição)
CAMPOS = [
    ("cpu", "Temperatura da CPU", "°C", 40, 110, 1),
    ("gpu", "Temperatura da GPU", "°C", 40, 110, 1),
    ("disco", "Temperatura dos discos", "°C", 30, 90, 1),
    ("ram", "Uso de RAM", "%", 50, 100, 1),
    ("cpu_uso", "Uso de CPU (por tempo prolongado)", "%", 50, 100, 1),
    ("livre_gb", "Espaço livre mínimo no C:", "GB", 1, 500, 1),
    ("proc_mb", "RAM de um único programa", "GB", 0.5, 64, 1024),
]


def comando_inicio():
    exe, args = caminhos.comando_app("--minimizado")
    return " ".join(f'"{a}"' if a != "--minimizado" else a for a in [exe, *args])


def inicio_ativo():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as k:
            winreg.QueryValueEx(k, NOME_RUN)
        return True
    except OSError:
        return False


def definir_inicio(ligar):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            winreg.SetValueEx(k, NOME_RUN, 0, winreg.REG_SZ, comando_inicio())
        else:
            try:
                winreg.DeleteValue(k, NOME_RUN)
            except FileNotFoundError:
                pass


class AbaConfig(ttk.Frame):
    def __init__(self, master, cfg, salvar):
        super().__init__(master, padding=12)
        self.cfg, self.salvar = cfg, salvar
        ttk.Label(self, text="Configurações", font=(ui.FONTE, 13, "bold")).pack(anchor="w")
        ttk.Label(self, text="Limites que disparam avisos no Resumo e notificações na bandeja.",
                  foreground=ui.Tema.p()["mut"]).pack(anchor="w")

        card = ui.Cartao(self)
        card.pack(fill="x", pady=10)
        grade = ttk.Frame(card, padding=14)
        grade.pack(fill="x")
        self.vars = {}
        for i, (chave, rotulo, un, mn, mx, fator) in enumerate(CAMPOS):
            ttk.Label(grade, text=rotulo).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 24))
            v = tk.StringVar()
            self.vars[chave] = v
            ttk.Entry(grade, textvariable=v, width=8).grid(row=i, column=1, pady=4)
            ttk.Label(grade, text=f"{un}   (de {mn:g} a {mx:g})",
                      foreground=ui.Tema.p()["mut"]).grid(row=i, column=2, sticky="w", padx=8)
        self.mostrar()

        btns = ttk.Frame(self)
        btns.pack(anchor="w")
        ttk.Button(btns, text="Salvar", command=self.gravar).pack(side="left")
        ttk.Button(btns, text="Restaurar padrão", command=self.restaurar).pack(side="left", padx=8)
        self.msg = ttk.Label(btns, text="", foreground=ui.Tema.p()["mut"])
        self.msg.pack(side="left", padx=8)

        ttk.Separator(self).pack(fill="x", pady=14)
        self.auto = tk.BooleanVar(value=inicio_ativo())
        ttk.Checkbutton(self, text="Iniciar com o Windows (abre direto na bandeja)",
                        variable=self.auto, command=self.alternar_inicio,
                        state="normal" if winreg else "disabled").pack(anchor="w")

    def mostrar(self):
        for chave, _, _, _, _, fator in CAMPOS:
            self.vars[chave].set(f"{historico.LIMITES[chave] / fator:g}")

    def gravar(self):
        novos = {}
        for chave, rotulo, _, mn, mx, fator in CAMPOS:
            try:
                n = float(self.vars[chave].get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Valor inválido", f"“{rotulo}” precisa ser um número.")
                return
            if not mn <= n <= mx:
                messagebox.showwarning("Valor inválido", f"“{rotulo}” deve ficar entre {mn:g} e {mx:g}.")
                return
            novos[chave] = n * fator
        historico.aplicar_limites(novos)
        self.cfg["limites"] = dict(historico.LIMITES)
        self.salvar()
        self.msg["text"] = "Salvo. Já vale para os próximos avisos."

    def restaurar(self):
        historico.aplicar_limites({})
        self.cfg.pop("limites", None)
        self.salvar()
        self.mostrar()
        self.msg["text"] = "Valores padrão restaurados."

    def alternar_inicio(self):
        try:
            definir_inicio(self.auto.get())
        except OSError as e:
            self.auto.set(not self.auto.get())
            messagebox.showerror("Erro", f"Não foi possível alterar o início automático:\n{e}")
