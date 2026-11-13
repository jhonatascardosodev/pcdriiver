"""Aba 'Meu PC': configuração do computador, periféricos detectados e lista manual."""
import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import caminhos
import ui

NOFLAG = 0x08000000
ARQ_MANUAL = caminhos.dado("perifericos.json")

TIPOS = ["Mouse", "Teclado", "Headset", "Fone de ouvido", "Microfone", "Caixa de som", "Webcam", "Monitor",
         "Controle / Gamepad", "Mousepad", "Cadeira", "Impressora", "Roteador / Rede", "Outro"]

SCRIPT = r'''
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$o = [ordered]@{}
$o.cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed)
$o.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM,
  @{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToString('yyyy-MM-dd')}}},
  CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate)
$o.vram = @(Get-ItemProperty 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' |
  Where-Object { $_.'HardwareInformation.qwMemorySize' } |
  ForEach-Object { [pscustomobject]@{Nome=$_.DriverDesc; Bytes=[uint64]$_.'HardwareInformation.qwMemorySize'} })
$o.ram = @(Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,Manufacturer,PartNumber,Capacity,ConfiguredClockSpeed,Speed,SMBIOSMemoryType)
$o.board = @(Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product)
$o.bios = @(Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion,@{n='Data';e={if($_.ReleaseDate){$_.ReleaseDate.ToString('yyyy-MM-dd')}}})
$o.disks = @(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,Size,HealthStatus)
$o.monitors = @(Get-CimInstance -Namespace root\wmi WmiMonitorID | ForEach-Object {
  [pscustomobject]@{
    Fab = (($_.ManufacturerName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '')
    Nome = (($_.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '')
  } })
$o.os = @(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture)
$all = @(Get-PnpDevice -PresentOnly)
$o.usb = @($all | Where-Object { $_.InstanceId -like 'USB\VID*' -and $_.InstanceId -notlike '*&MI_*' } | ForEach-Object {
  $vp = ($_.InstanceId -split '\\')[1]
  $prod = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_BusReportedDeviceDesc').Data
  if (-not $prod) { $prod = $_.FriendlyName }
  $cls = @($all | Where-Object { $_.InstanceId -like "*$vp*" } | ForEach-Object { $_.Class } | Sort-Object -Unique)
  [pscustomobject]@{ Produto = $prod; Id = $vp; Classes = $cls }
})
$o.audio = @($all | Where-Object { $_.Class -eq 'AudioEndpoint' } | ForEach-Object { $_.FriendlyName })
$o.cams = @($all | Where-Object { $_.Class -in 'Camera','Image' } | ForEach-Object { $_.FriendlyName })
$o | ConvertTo-Json -Depth 5 -Compress
'''

FAB_MONITOR = {"DEL": "Dell", "SAM": "Samsung", "GSM": "LG", "AOC": "AOC", "ACR": "Acer", "BNQ": "BenQ",
               "LEN": "Lenovo", "HWP": "HP", "PHL": "Philips", "MSI": "MSI", "GBT": "Gigabyte", "AUS": "ASUS",
               "ENC": "Eizo", "VSC": "ViewSonic", "IVM": "Iiyama", "SNY": "Sony"}
TIPO_RAM = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}


def coletar():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", SCRIPT],
                       capture_output=True, timeout=180, creationflags=NOFLAG)
    return json.loads(r.stdout.decode("utf-8", "replace"))


def _l(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def _gb(n, casas=0):
    return f"{n / 1024**3:.{casas}f} GB"


def nome_monitor(m):
    fab = FAB_MONITOR.get(m["Fab"], m["Fab"])
    nome = m["Nome"].strip()
    return nome if nome.lower().startswith(fab.lower()) else f"{fab} {nome}".strip()


def _versao_nvidia(v):
    """32.0.15.8228 -> 582.28 (formato que a NVIDIA mostra)."""
    try:
        d = "".join(v.split(".")[-2:])[-5:]
        return f"{d[:3]}.{d[3:]}"
    except Exception:
        return v


MOUSE_DICAS = ("mouse", "pulsefire", "deathadder", "viper", "basilisk", "g502", "g305", "g203", "g pro",
               "glorious", "model o", "zowie", "naga", "rato")
TECLADO_DICAS = ("keyboard", "teclado", "keychron", "huntsman", "blackwidow", "apex", "k552", "k70")


def tipo_usb(classes, nome=""):
    c = {x.lower() for x in _l(classes)}
    n = nome.lower()
    if "mouse" in c or "keyboard" in c:
        # um mouse gamer costuma expor também uma interface de teclado (e vice-versa),
        # então o nome do produto decide quando dá
        if any(k in n for k in TECLADO_DICAS):
            return "Teclado"
        if any(k in n for k in MOUSE_DICAS):
            return "Mouse"
        return "Mouse" if c == {"mouse"} else "Teclado" if c == {"keyboard"} else "Mouse / Teclado"
    if c & {"camera", "image"}:
        return "Webcam"
    if c & {"media", "audioendpoint"}:
        return "Áudio"
    if "bluetooth" in c:
        return "Bluetooth"
    if c & {"diskdrive", "wpd"}:
        return "Armazenamento USB"
    return "Dispositivo USB"


def montar_secoes(d):
    """Transforma o JSON do PowerShell em [(título, [(rótulo, valor)])]."""
    s = []
    cpu = _l(d.get("cpu"))
    if cpu:
        c = cpu[0]
        s.append(("Processador", [("Modelo", c["Name"].replace("(R)", "").replace("(TM)", "").replace("  ", " ")),
                                  ("Núcleos / threads", f"{c['NumberOfCores']} / {c['NumberOfLogicalProcessors']}"),
                                  ("Clock base", f"{c['MaxClockSpeed'] / 1000:.2f} GHz")]))
    vram = {v["Nome"]: v["Bytes"] for v in _l(d.get("vram"))}
    for g in _l(d.get("gpu")):
        linhas = [("Modelo", g["Name"])]
        mem = vram.get(g["Name"]) or g.get("AdapterRAM")
        if mem:
            linhas.append(("Memória de vídeo", _gb(mem)))
        ver = g.get("DriverVersion") or ""
        if "nvidia" in g["Name"].lower():
            ver = f"{_versao_nvidia(ver)}  (Windows: {ver})"
        linhas.append(("Driver", f"{ver}  •  {g.get('DriverDate') or '?'}"))
        if g.get("CurrentHorizontalResolution"):
            linhas.append(("Resolução atual", f"{g['CurrentHorizontalResolution']}×{g['CurrentVerticalResolution']} "
                                              f"@ {g['CurrentRefreshRate']} Hz"))
        s.append(("Placa de vídeo", linhas))
    ram = _l(d.get("ram"))
    if ram:
        total = sum(m["Capacity"] for m in ram)
        vel = ram[0].get("ConfiguredClockSpeed") or ram[0].get("Speed")
        tipo = TIPO_RAM.get(ram[0].get("SMBIOSMemoryType"), "")
        linhas = [("Total", f"{_gb(total)}  {tipo}  {vel or '?'} MHz".replace("  ", " ").strip())]
        for m in ram:
            linhas.append((m["DeviceLocator"], f"{_gb(m['Capacity'])} • {m['Manufacturer']} • {str(m['PartNumber']).strip()}"))
        s.append(("Memória RAM", linhas))
    placa = _l(d.get("board"))
    bios = _l(d.get("bios"))
    if placa:
        linhas = [("Modelo", f"{placa[0]['Manufacturer']} {placa[0]['Product']}")]
        if bios:
            linhas.append(("BIOS", f"{bios[0]['SMBIOSBIOSVersion']}  •  {bios[0].get('Data') or '?'}"))
        s.append(("Placa-mãe", linhas))
    discos = _l(d.get("disks"))
    if discos:
        s.append(("Armazenamento", [(x["FriendlyName"].replace("ATA ", ""),
                                     f"{x['MediaType']} • {_gb(x['Size'])} • {x['HealthStatus']}") for x in discos]))
    mons = _l(d.get("monitors"))
    if mons:
        s.append(("Monitor", [(f"Monitor {i + 1}", nome_monitor(m)) for i, m in enumerate(mons)]))
    so = _l(d.get("os"))
    if so:
        s.append(("Sistema", [("Windows", f"{so[0]['Caption'].replace('Microsoft ', '')}  •  {so[0]['OSArchitecture']}"),
                              ("Versão", so[0]["Version"])]))
    return s


def detectados(d):
    """[(tipo, nome, id)] de periféricos encontrados pelo Windows."""
    res = []
    for u in _l(d.get("usb")):
        nome = u["Produto"] or ""
        if any(x in nome.lower() for x in ("desconhecido", "unknown")):
            continue  # entradas fantasmas do Windows
        tipo = "Hub USB" if "hub" in nome.lower() else tipo_usb(u.get("Classes"), nome)
        res.append((tipo, nome, u["Id"]))
    for m in _l(d.get("monitors")):
        res.append(("Monitor", nome_monitor(m), ""))
    for a in _l(d.get("audio")):
        res.append(("Áudio", a, ""))
    for c in _l(d.get("cams")):
        res.append(("Webcam", c, ""))
    return res


def ler_manual():
    try:
        with open(ARQ_MANUAL, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar_manual(lista):
    with open(ARQ_MANUAL, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)


class DialogoPeriferico(tk.Toplevel):
    """Janela para adicionar/editar um periférico."""

    def __init__(self, master, valores=None):
        super().__init__(master)
        self.title("Periférico")
        self.configure(bg=ui.Tema.p()["bg"])
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.resultado = None
        v = valores or {"tipo": TIPOS[0], "modelo": "", "obs": ""}
        f = ttk.Frame(self, padding=16)
        f.pack()
        ttk.Label(f, text="Tipo").grid(row=0, column=0, sticky="w", pady=4)
        self.tipo = ttk.Combobox(f, values=TIPOS, width=34)
        self.tipo.set(v["tipo"])
        self.tipo.grid(row=0, column=1, pady=4, padx=(10, 0))
        ttk.Label(f, text="Marca / modelo").grid(row=1, column=0, sticky="w", pady=4)
        self.modelo = ttk.Entry(f, width=37)
        self.modelo.insert(0, v["modelo"])
        self.modelo.grid(row=1, column=1, pady=4, padx=(10, 0))
        ttk.Label(f, text="Observação").grid(row=2, column=0, sticky="w", pady=4)
        self.obs = ttk.Entry(f, width=37)
        self.obs.insert(0, v.get("obs", ""))
        self.obs.grid(row=2, column=1, pady=4, padx=(10, 0))
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Cancelar", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(b, text="Salvar", style="Accent.TButton", command=self.salvar).pack(side="left")
        self.modelo.focus_set()
        self.bind("<Return>", lambda e: self.salvar())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_visibility()

    def salvar(self):
        modelo = self.modelo.get().strip()
        if not modelo:
            messagebox.showwarning("Faltou o modelo", "Digite a marca/modelo do periférico.", parent=self)
            return
        self.resultado = {"tipo": self.tipo.get().strip() or "Outro", "modelo": modelo, "obs": self.obs.get().strip()}
        self.destroy()


class AbaMeuPC(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        self.carregada = False
        self.dados = None
        self.secoes = []
        topo = ttk.Frame(self)
        topo.pack(fill="x")
        ttk.Label(topo, text="Meu PC", font=(ui.FONTE, 13, "bold")).pack(side="left")
        self.lbl = ttk.Label(topo, text="", foreground=ui.Tema.p()["mut"])
        self.lbl.pack(side="left", padx=12)
        ttk.Button(topo, text="Copiar especificações", command=self.copiar).pack(side="right")
        ttk.Button(topo, text="Atualizar", command=self.carregar).pack(side="right", padx=6)
        self.area = ui.AreaRolavel(self)
        self.area.pack(fill="both", expand=True, pady=(8, 0))
        self.corpo = self.area.interior
        self.corpo.columnconfigure(0, weight=1, uniform="c")
        self.corpo.columnconfigure(1, weight=1, uniform="c")

    # ---------- carregar ----------
    def carregar(self):
        self.lbl["text"] = "Lendo o hardware... (alguns segundos)"
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            d = coletar()
        except Exception as e:
            msg = f"Erro ao ler o hardware: {e}"
            self.after(0, lambda: self.lbl.configure(text=msg))
            return
        self.after(0, self.mostrar, d)

    def mostrar(self, d):
        self.carregada = True
        self.dados = d
        self.secoes = montar_secoes(d)
        for w in self.corpo.winfo_children():
            w.destroy()
        for i, (titulo, linhas) in enumerate(self.secoes):
            self._cartao(titulo, linhas).grid(row=i // 2, column=i % 2, sticky="nsew",
                                              padx=(0, 10) if i % 2 == 0 else 0, pady=(0, 10))
        linha = (len(self.secoes) + 1) // 2
        self._cartao_detectados().grid(row=linha, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self._cartao_manual().grid(row=linha + 1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self.lbl["text"] = "Lido agora"
        ui.restilizar(self.corpo)

    def _cartao(self, titulo, linhas):
        c = ui.Cartao(self.corpo)
        ui.Texto(c, titulo, 11, True, cor="acc").grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
        for i, (rot, val) in enumerate(linhas, start=1):
            ui.Texto(c, rot, 9, cor="mut").grid(row=i, column=0, sticky="nw", padx=(14, 10), pady=2)
            t = ui.Texto(c, val, 10)
            t.configure(wraplength=330, justify="left")
            t.grid(row=i, column=1, sticky="w", pady=2, padx=(0, 14))
        ui.Texto(c, "", 4).grid(row=len(linhas) + 1, column=0)
        return c

    def _cartao_detectados(self):
        c = ui.Cartao(self.corpo)
        ui.Texto(c, "Periféricos detectados pelo Windows", 11, True, cor="acc").pack(anchor="w", padx=14, pady=(12, 0))
        ui.Texto(c, "Mouse e teclado USB mostram o nome que o próprio aparelho informa. Se o seu não aparece "
                    "ou vem genérico, use a lista abaixo.", 9, cor="mut").pack(anchor="w", padx=14, pady=(0, 6))
        frame, self.det_tree = ui.criar_tree(c, ("Tipo", "Dispositivo", "ID USB"), (150, 470, 200), altura=6)
        frame.pack(fill="x", padx=14)
        for tipo, nome, vid in detectados(self.dados):
            self.det_tree.insert("", "end", values=(tipo, nome, vid))
        ui.reordenar(self.det_tree)
        ttk.Button(c, text="Adicionar o selecionado à minha lista", command=self.adicionar_detectado).pack(
            anchor="w", padx=14, pady=10)
        return c

    def _cartao_manual(self):
        c = ui.Cartao(self.corpo)
        ui.Texto(c, "Meus periféricos (lista manual)", 11, True, cor="acc").pack(anchor="w", padx=14, pady=(12, 0))
        ui.Texto(c, "Para o que o Windows não consegue identificar: headset, caixa de som, mousepad, controle, "
                    "cadeira... Fica salvo neste computador.", 9, cor="mut").pack(anchor="w", padx=14, pady=(0, 6))
        frame, self.man_tree = ui.criar_tree(c, ("Tipo", "Marca / modelo", "Observação"), (150, 400, 270), altura=6)
        frame.pack(fill="x", padx=14)
        self.man_tree.bind("<Double-1>", lambda e: self.editar())
        b = ttk.Frame(c)
        b.pack(anchor="w", padx=14, pady=10)
        ttk.Button(b, text="Adicionar", style="Accent.TButton", command=self.adicionar).pack(side="left")
        ttk.Button(b, text="Editar", command=self.editar).pack(side="left", padx=6)
        ttk.Button(b, text="Remover", command=self.remover).pack(side="left")
        self.render_manual()
        return c

    # ---------- lista manual ----------
    def render_manual(self):
        self.man_tree.delete(*self.man_tree.get_children())
        for i, p in enumerate(ler_manual()):
            self.man_tree.insert("", "end", iid=str(i), values=(p["tipo"], p["modelo"], p.get("obs", "")))
        ui.reordenar(self.man_tree)

    def adicionar(self, valores=None):
        dlg = DialogoPeriferico(self, valores)
        self.wait_window(dlg)
        if dlg.resultado:
            lista = ler_manual()
            lista.append(dlg.resultado)
            salvar_manual(lista)
            self.render_manual()

    def adicionar_detectado(self):
        sel = self.det_tree.selection()
        if not sel:
            messagebox.showinfo("Selecione", "Clique primeiro em um item da lista de detectados.")
            return
        tipo, nome, _ = self.det_tree.item(sel[0])["values"][:3]
        tipo = str(tipo) if str(tipo) in TIPOS else "Outro"
        self.adicionar({"tipo": tipo, "modelo": str(nome), "obs": ""})

    def editar(self):
        sel = self.man_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        lista = ler_manual()
        if idx >= len(lista):
            return
        dlg = DialogoPeriferico(self, lista[idx])
        self.wait_window(dlg)
        if dlg.resultado:
            lista[idx] = dlg.resultado
            salvar_manual(lista)
            self.render_manual()

    def remover(self):
        sel = self.man_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        lista = ler_manual()
        if idx < len(lista) and messagebox.askyesno("Remover", f"Remover '{lista[idx]['modelo']}' da lista?"):
            lista.pop(idx)
            salvar_manual(lista)
            self.render_manual()

    # ---------- copiar ----------
    def copiar(self):
        if not self.secoes:
            return
        linhas = []
        for titulo, itens in self.secoes:
            linhas.append(titulo.upper())
            linhas += [f"  {r}: {v}" for r, v in itens]
            linhas.append("")
        linhas.append("PERIFÉRICOS")
        linhas += [f"  {t}: {n}" for t, n, _ in detectados(self.dados) if t not in ("Hub USB",)]
        linhas += [f"  {p['tipo']}: {p['modelo']}" for p in ler_manual()]
        self.clipboard_clear()
        self.clipboard_append("\n".join(linhas))
        self.lbl["text"] = "Especificações copiadas para a área de transferência"
