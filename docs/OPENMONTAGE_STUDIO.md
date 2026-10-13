# OpenMontage Studio

Abra `OpenMontageStudio.bat` ou o atalho **OpenMontage Studio** na Área de
Trabalho. A interface usa Tkinter incluído no Python e não instala dependências
adicionais.

## Modos

- **Criar vídeo**: prepare tema, descrição, duração e texto de narração. Nesta
  etapa, o app gera e mixa áudio local e abre a montagem manual para exportar
  MP4 com mídias fornecidas pelo usuário. Não cria roteiro automaticamente.
- **Editar vídeo bruto**: selecione um arquivo local para registrar a origem. O
  arquivo é tratado como somente leitura e pode ser adicionado à montagem
  manual. O app não analisa nem edita automaticamente o vídeo bruto.
- **Produção personalizada**: reúna as preferências do projeto. Duração em
  horas, minutos e segundos é validada e exibida como planejamento. Duração
  aproximada e alvo rígido ainda não controlam renderização nem mixagem. A
  montagem local tem durações próprias e acompanha o WAV escolhido.

## Preferências e áudio integrado

Idioma, legendas e estilo visual são configurações preparatórias. O runner
Kokoro desta instalação fixa `lang_code="a"`, portanto só gera inglês. Se outro
idioma estiver selecionado, a geração de narração é bloqueada com uma mensagem
explicativa. Legendas e estilo não são aplicados ao áudio nem geram vídeo.

O texto da narração é fornecido pelo usuário; não há geração automática de
roteiro. As vozes disponíveis na interface são `af_heart`, `am_echo` e
`am_michael`, usadas nos testes locais existentes.

A música é selecionada de forma determinística no catálogo JSON pela emoção e
só considera arquivos que existem. A mixagem FFmpeg mantém o perfil aprovado:
narração +3 dB, ducking −35 dB, ganho final +3 dB, sem normalização automática,
limitador de pico de amostra a −1 dBFS. A duração do áudio acompanha a duração
efetiva da narração; a duração planejada não estica uma fala curta.

O catálogo padrão fica em
`D:\YouTube-Automacao\Musicas\catalogo_musical.json`; use o botão `…` para
escolher outro. Os metadados atuais não comprovam a licença das faixas. Confirme
origem e licença antes de incluir música em vídeos monetizados.

## Montagem local e MP4 — Etapa 3

Disponível nos três modos, em uma janela de montagem compartilhada:

1. Abra **Montagem local** e adicione imagens e clipes locais.
2. Use **Subir**, **Descer** e **Remover** para organizar a timeline. Remover
   um item da lista não exclui o arquivo original.
3. Selecione um item, defina sua duração em segundos, escolha **Corte**,
   **Crossfade** ou **Fade por preto** e clique em **Aplicar ao item**.
4. Use **Ajustar ao WAV**. O padrão é o WAV aprovado em
   `D:\YouTube-Automacao\Audios\audio_final_documentario.wav`.
5. Clique em **Exportar MP4…**, escolha um nome novo e aguarde a verificação.
   **Abrir MP4** fica disponível após o sucesso.

A exportação local usa FFmpeg: **1920×1080, H.264, 30 fps, yuv420p**, com
áudio AAC a 192 kbps. O WAV inteiro é usado somente como entrada. A conversão
para AAC é com perdas; não há nova mixagem, normalização, ganho, ducking ou
efeito. O vídeo termina no quadro que cobre o fim do WAV: diferença inferior
a 1/30 de segundo.

As transições sobrepõem os itens e reduzem a duração total. A transição do
último item é ignorada. Cada clipe começa no início, é cortado se necessário
ou mantém seu último quadro quando é curto. O áudio dos clipes é ignorado.
As mídias mantêm proporção, com barras pretas quando necessário.

Arquivos existentes não são sobrescritos, inclusive se outro processo criar
o destino durante a exportação. É possível cancelar; o exportador remove
somente seus temporários e uma eventual saída incompleta criada por ele.
Fechar a janela de montagem mantém os itens enquanto o Studio estiver aberto.
Ainda não há salvamento da timeline entre sessões nem prévia integrada.

## Ainda não integrado

Pesquisa e geração de roteiro, busca de imagens/vídeos, análise de vídeo bruto,
edição automática e transcrição/legendas não fazem parte desta etapa.
Os modos e preferências deixam essas escolhas visíveis
sem simular operações. Para produção audiovisual completa, use o pipeline
`documentary-montage` guiado do OpenMontage, com seus diretores de etapa e
checkpoints.

## Diagnóstico e saída

O TTS requer `D:\YouTube-Automacao\.venv-kokoro\Scripts\python.exe` e
`D:\YouTube-Automacao\kokoro_runner.py`. A mixagem requer `ffmpeg` e `ffprobe`
disponíveis no PATH. Mensagens e erros aparecem na janela e no log inferior.
Por padrão, os arquivos de áudio são gravados em
`projects/openmontage-studio/audio/`; nomes incluem tema e horário para evitar
sobrescrever saídas anteriores.

Os MP4 usam por padrão `projects/openmontage-studio/renders/`. A montagem
requer `ffmpeg` e `ffprobe` no PATH, incluindo libx264, AAC e xfade.
`StudioExport.check_available()` retorna um booleano e delega ao contrato
`BaseTool.get_status()`. Essa consulta verifica os executáveis; a exportação
real verifica os codecs, filtros e o arquivo produzido.

## Validação de 13/10/2026

105 testes do escopo passaram (interface Tk, timeline, exportação, proteção de
arquivos, disponibilidade e regressão de áudio). O validador
`scripts/validate_studio_stage3.py` exportou um novo MP4 usando o WAV aprovado
inteiro, com 3,775 s de áudio e 114 quadros/3,800 s de vídeo. A decodificação
completa passou e o áudio decodificado foi idêntico à conversão direta do WAV
para AAC. Os quadros amostrados do MP4 foram inspecionados.

O iniciador abriu o processo e o atalho foi conferido. A captura visual da
janela pelo helper Windows falhou com `FrameArrived timed out`; a inspeção
visual manual da janela permanece pendente, embora os testes com widgets
reais e a exportação pela interface tenham passado. Vídeos de 8–20 minutos
e a audição humana do MP4 não foram validados nesta rodada.

Detalhes e evidências em [RELATORIO_ETAPA3_20261013.md](RELATORIO_ETAPA3_20261013.md).
A Etapa 4 não foi iniciada.
