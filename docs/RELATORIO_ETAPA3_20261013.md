# Etapa 3 — correção e validação em 13/10/2026

O erro `StudioExport.check_available` foi reproduzido e corrigido. A montagem
local e a exportação MP4 Full HD passaram nos testes automatizados e em uma
exportação real pela interface Tk com o WAV aprovado inteiro. A inspeção
visual manual da janela e a audição humana permanecem pendentes. A Etapa 4
não foi iniciada.

## Revisão e correção

Foram lidos o guia, o plano, as instruções locais e a documentação antes das
edições. A revisão encontrou a timeline, o editor Tk e o exportador já
implementados, com testes e uma exportação anterior preservada. Foram
conferidos o modelo de quadros, a ordenação, as sobreposições, a sincronização,
o tratamento de cancelamento, a proteção contra sobrescrita e as alterações
anteriores da integração de áudio. A documentação ainda descrevia a Etapa 2.

O erro reproduzido foi:

```text
AttributeError: 'StudioExport' object has no attribute 'check_available'
```

`BaseTool` oferece `get_status()` e `check_dependencies()`, mas não
`check_available()`. Foi acrescentado ao `StudioExport` um método booleano
de compatibilidade que delega a `get_status()`, preservando a verificação
central de dependências. Não foi necessário mudar o motor de renderização.
O método verifica os executáveis; não certifica sozinho codecs e filtros.
Na instalação testada retorna `True`, coerente com `get_status(): available`.

Arquivos alterados nesta rodada:

- `tools/video/studio_export.py`: método de compatibilidade.
- `tests/tools/test_studio_export_availability.py`: cinco testes novos,
  inclusive ausência de FFmpeg, ffprobe, ambos e atualização de disponibilidade.
- `scripts/validate_studio_stage3.py`: verifica disponibilidade e compara o
  áudio exportado com uma conversão direta do WAV para AAC.
- `docs/OPENMONTAGE_STUDIO.md` e `PLANO_OPENMONTAGE_STUDIO.txt`: funcionamento,
  resultados e pendências atualizados, com histórico do plano preservado.
- Este relatório.

O mixer, seus ganhos, o WAV, o iniciador e os renderizadores do pipeline não
foram alterados nesta rodada. Não houve geração TTS nova, API paga, instalação
de dependências ou publicação.

## Testes automatizados

Ambiente: Python 3.11.3, Windows, FFmpeg 9.0.2 full build.

Antes da correção: **100 passaram em 43,91 s**.
Após a correção: **105 passaram em 36,10 s**, sem falhas ou testes ignorados.
Esse total cobre o escopo abaixo, não a suíte inteira do repositório.

| Grupo | Testes aprovados |
|---|---:|
| Configurações, navegação e seleção local do Studio | 13 |
| Timeline, duração em quadros, ordem e ajuste ao WAV | 21 |
| Widgets Tk, fechamento/reabertura, erros e worker | 8 |
| Exportações reais FFmpeg e proteção de arquivos | 10 |
| Disponibilidade do StudioExport | 5 |
| Mixagem documental, ducking, loudness, fades, duração e biblioteca | 45 |
| Dependências do BaseTool | 3 |
| **Total** | **105** |

Os testes reais de exportação verificam corte, crossfade e fade por preto,
decodificação completa, proporção de clipe vertical, retenção do último quadro,
descarte do áudio original do clipe, cancelamento de FFmpeg, falha de render,
destino já existente e destino criado por outro processo durante o render.
Os testes de interface usam widgets Tk reais; cenários de retorno do worker
também usam mocks. O validador separado executou o exportador real pelo botão
da interface, com seleção do caminho de saída automatizada.

Comando reproduzível usado após a correção:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_openmontage_studio.py tests/test_studio_timeline.py tests/test_studio_timeline_ui.py tests/tools/test_studio_export.py tests/tools/test_studio_export_availability.py tests/tools/test_documentary_audio_mix.py tests/tools/test_audio_mixer_ducking.py tests/tools/test_audio_mixer_loudnorm_target.py tests/tools/test_audio_mixer_segmented_music.py tests/tools/test_audio_mixer_target_duration.py tests/tools/test_audio_mixer_track_fades.py tests/tools/test_music_library.py tests/tools/test_base_tool_dependencies.py -q --junitxml=projects/openmontage-studio/qa-stage3-20261013-151636-247279/pytest-results.xml
.venv/Scripts/python.exe scripts/validate_studio_stage3.py
```

Também passaram `py_compile` dos arquivos Python alterados/criados e
`git diff --check` (este último cobre os arquivos rastreados pelo Git).

## MP4 e áudio

Novo arquivo: [timeline-approved-wav-1080p.mp4](../projects/openmontage-studio/qa-stage3-20261013-151636-247279/timeline-approved-wav-1080p.mp4).

| Medida | Resultado |
|---|---|
| Resolução | 1920×1080 |
| Vídeo | H.264, yuv420p, 30 fps |
| Quadros / duração de vídeo | 114 / 3,800 s |
| Áudio | AAC, 192 kbps configurados, 3,775 s |
| Diferença de duração | 25 ms, inferior a um quadro |
| Tamanho | 210.567 bytes |
| Decodificação de todos os quadros/amostras | Aprovada, sem erro |
| Comparação com AAC direto do WAV | PCM decodificado idêntico |

A amostra usa três imagens sintéticas e um clipe vertical de teste com áudio
próprio, mais o WAV aprovado completo. Os quadros amostrados foram inspecionados:
sequência vermelho → clipe → azul → verde, com crossfade, fade por preto e corte.
O quadro preto final da folha de contato é uma célula vazia do mosaico 4×4.
Este é um artefato de QA, não um documentário final.

A conversão AAC é com perdas; a igualdade foi medida contra outra conversão
AAC com os mesmos parâmetros, não contra os bytes PCM originais do WAV.
Isso verifica que a exportação não acrescentou mixagem, ganho ou efeitos.
Não houve audição humana nesta rodada.

## Interface e iniciador

Navegação entre os modos, edição/remoção/reordenação, ajuste ao WAV, habilitação
dos botões, erros, cancelamento e conservação da timeline ao fechar/reabrir
passaram nos testes. A exportação real foi acionada pelo botão do editor e
terminou com `Abrir MP4` habilitado.

`OpenMontageStudio.bat` iniciou o processo e a janela `OpenMontage Studio`
foi identificada. O atalho da Área de Trabalho aponta para esse BAT e para
o diretório correto do projeto. O sistema de captura Windows primeiro
informou janela minimizada; após ativação e recuperação, falhou com
`FrameArrived timed out: timed out waiting on channel`.
Portanto, o layout visível da janela e a reprodução no player do Windows
não foram certificados nesta rodada. Essa falha é do mecanismo de captura;
não foi demonstrada falha do app.

## Preservação

Backup novo, anterior às edições:
`backups/studio-stage3-fix-20261013-151508-127/`.

O manifesto inicial registra 43 arquivos. **42 arquivos estáticos mantiveram
SHA-256, tamanho e data de modificação**, incluindo backups anteriores, WAVs,
mídias/MP4 de QA anteriores, configuração e arquivos de áudio protegidos.
O 43º arquivo, `projects/openmontage-studio/events.jsonl`, cresceu de 581 para
1.162 bytes com os eventos da nova execução; os 581 bytes originais foram
verificados por SHA-256 e permanecem idênticos. Nenhum registro foi removido.
As novas mídias de teste também mantiveram seus hashes após a exportação.

WAV aprovado, usado somente como entrada:
`D:\YouTube-Automacao\Audios\audio_final_documentario.wav`.

```text
SHA-256: 82808d024b02236e0eff891ff74d6d05879715e3e1bc13c2f667869dbe80692c
Tamanho: 181278 bytes
```

## Evidências e pendências

Evidências em `projects/openmontage-studio/qa-stage3-20261013-151636-247279/`:

- `pytest-results.xml`: resultado dos 105 testes.
- `validation.json`: codecs, durações, timeline, hashes e comparação de áudio.
- `preservation-after.json` e `events-preservation.json`: verificação de preservação.
- `frames.png`: folha de contato do novo MP4.
- `approved-wav-aac-reference.m4a`: referência de comparação, derivada sem alterar o WAV.

Pendências de validação: inspeção visual manual da janela, audição humana e
abertura/reprodução no player do Windows. O WAV atual tem apenas 3,775 s;
desempenho, consumo de disco e uso prolongado com timelines de 8–20 minutos
não foram medidos.

Limitações já existentes: sem salvamento da timeline entre sessões, prévia
integrada, escolha do ponto inicial do clipe ou edição automática. Pesquisa,
roteiro automático, legendagem e novos idiomas continuam fora desta etapa.
Nenhum desses recursos foi apresentado como pronto. A Etapa 4 permanece
sem início.
