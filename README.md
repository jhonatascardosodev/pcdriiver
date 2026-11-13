# Monitor PC

Painel para Windows que mostra, em tempo real, o que está pesando no seu computador: CPU, memória, disco, temperaturas e processos. Fica na bandeja do sistema registrando o histórico e avisa quando algo passa do limite.

Feito em Python com tkinter, com tema escuro/claro e gráficos interativos.

<!-- Capturas de tela: salve em docs/ e descomente as linhas abaixo
![Resumo (tema escuro)](docs/resumo-escuro.png)
![Resumo (tema claro)](docs/resumo-claro.png)
-->

## Download

Sem Python instalado? Baixe o `MonitorPC.exe` na página de [Releases](https://github.com/jhonatascardosodev/pcdriiver/releases/latest) e dê dois cliques. Não há instalador: o programa é um arquivo único, e os dados ficam na mesma pasta dele.

O arquivo não é assinado, então o Windows SmartScreen pode avisar na primeira vez. Clique em **Mais informações** e depois em **Executar assim mesmo**. O código-fonte está neste repositório, e você pode gerar o `.exe` por conta própria (veja [Gerar o .exe](#gerar-o-exe-opcional)).

## Recursos

| Aba | O que faz |
|---|---|
| **Resumo** | Medidores de CPU, RAM e disco C:, cartões de temperatura, gráfico ao vivo e avisos |
| **Meu PC** | Ficha técnica: processador, placa de vídeo (com VRAM e versão do driver), memória, placa-mãe, BIOS, discos, monitor e sistema. Detecta mouse, teclado e áudio pelo nome real e permite montar uma lista própria de periféricos |
| **Processos** | Lista ordenável dos processos que mais usam memória e CPU |
| **Histórico** | Gráfico de uso ao longo do tempo; ao passar o mouse mostra quais processos pesavam naquele momento |
| **Disco** | Analisador de pastas para descobrir o que ocupa espaço |
| **Limpeza** | Remove arquivos temporários, caches de navegador, lixeira, cache do npm e da NVIDIA, com confirmação antes de apagar |
| **Temperaturas** | Sensores de CPU, GPU, discos e ventoinhas |
| **Drivers** | Lista de drivers instalados com versão e data |
| **Sistema** | Mostra o pagefile e permite movê-lo do HDD para o SSD |
| **Configurações** | Ajusta os limites dos alertas e liga o início automático com o Windows |

**Bandeja do sistema:** ao fechar a janela, o programa continua rodando, coleta o histórico a cada 10 segundos e envia notificações quando:

- a temperatura de CPU ou GPU passa de 85 °C ou a do disco de 60 °C;
- a RAM passa de 90% ou a CPU fica acima de 90% por tempo prolongado;
- o disco C: tem menos de 5 GB livres;
- um processo usa 4 GB de memória ou mais.

Esses são os valores padrão; todos podem ser alterados na aba **Configurações**.

## Configurações

- **Limites dos alertas:** temperatura de CPU, GPU e discos, uso de RAM e de CPU, espaço livre mínimo no C: e RAM de um único programa. Valem na hora para os avisos do Resumo e para as notificações da bandeja, e há um botão para restaurar o padrão.
- **Iniciar com o Windows:** a caixa de seleção cria uma entrada no registro do usuário (sem precisar de administrador) e o programa abre direto na bandeja, com a opção `--minimizado`. Se mudar a pasta do projeto ou a versão do Python, desligue e ligue a opção de novo.

## Requisitos

- Windows 10 ou 11
- Python 3.10 ou superior
- Para temperaturas: [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) (opcional, veja abaixo)

## Instalação

```
git clone https://github.com/jhonatascardosodev/pcdriiver.git
cd pcdriiver
pip install -r requirements.txt
py app.py
```

Ou dê dois cliques em `iniciar.bat`.

## Gerar o .exe (opcional)

Para rodar sem Python instalado, dê dois cliques em `build.bat`. Ele usa o PyInstaller e cria `dist\MonitorPC.exe`, um arquivo único. O histórico, o `config.json` e a lista de periféricos passam a ficar na mesma pasta do `.exe`, então mantenha-o numa pasta sua (não em `dist`, que é apagada ao refazer o build).

## Temperaturas (opcional)

O Windows não expõe temperaturas de forma padrão, então o programa lê os dados do LibreHardwareMonitor:

1. Instale: `winget install LibreHardwareMonitor.LibreHardwareMonitor`
2. Abra o LibreHardwareMonitor **como administrador**.
3. No menu **Options**, ative **Remote Web Server** (porta 8085).
4. Deixe-o aberto. O Monitor PC passa a mostrar os sensores automaticamente.

Sem isso, o restante do programa funciona normalmente; só as temperaturas ficam indisponíveis.

## Permissões de administrador

Rode como administrador apenas para:

- limpar a pasta temporária do Windows;
- mover o pagefile (exige reiniciar o PC em seguida).

A aba **Sistema** tem o botão "Reiniciar como administrador".

## Dados locais

O programa grava na própria pasta (ou ao lado do `.exe`), e estes arquivos não vão para o Git:

- `historico.db`: histórico de uso (SQLite);
- `perifericos.json`: sua lista de periféricos;
- `config.json`: tema, tamanho da janela e limites dos alertas.

## Estrutura

| Arquivo | Conteúdo |
|---|---|
| `app.py` | Janela principal e abas |
| `ui.py` | Temas e componentes visuais (medidores, gráficos, tabelas) |
| `meupc.py` | Aba Meu PC e leitura de hardware |
| `abas_extra.py` | Abas Histórico, Limpeza e Sistema |
| `config_aba.py` | Aba Configurações (limites e início com o Windows) |
| `historico.py` | Coleta, banco de dados, sensores e alertas |
| `caminhos.py` | Onde ficam os dados e como o programa se reabre (código ou `.exe`) |
| `tray.py` | Ícone da bandeja |
| `build.bat` | Gera o `.exe` com PyInstaller |

## Limitações

- O nome da placa-mãe aparece como a BIOS informa (às vezes genérico, como "OEM H110").
- Headset analógico, mousepad e similares não são detectáveis; use a lista manual.
- O medidor e o alerta de espaço livre usam apenas o disco C:.

## Licença

[MIT](LICENSE)
