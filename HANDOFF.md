# HANDOFF — OpenMontage Studio (Etapa 8 / 8.1)

Documento de transferência do estado atual do **OpenMontage Studio**, o fluxo local do OpenMontage para automatizar documentários de 8–20 minutos para o YouTube, com narração/mixagem aprovadas e montagem não destrutiva.

**Última retomada: 2026-10-14.** Etapa 8 concluída: motor de animação Stickman (personagens articulados SVG + GSAP) integrado à montagem — 2 personagens, 4 cenários, 11 ações, 4 presets, demo 20 s renderizada como MP4 silencioso 1920×1080 · 30 fps, com associação ao plano e à timeline. Antes disso, cenas HyperFrames de teste (seção 9) e correções stock (seção 8). O estado continua sem commit.

---

## 1. Contexto

O Studio é uma aplicação Tkinter isolada do pipeline orquestrado (`pipeline_defs/`):

- **Áudio local:** narração Kokoro (inglês) + seleção de música por catálogo local + mixagem com perfil aprovado fixo.
- **Montagem local:** timeline por quadros (30 fps, 1080p), transições cut/crossfade/fade, encaixe exato no WAV via `Ajustar ao WAV`, exportação MP4 H.264/AAC com verificação.
- **Gerador de plano:** a partir do texto da narração, cria um `scenes.json` de planejamento (cenas sem `media`) com durações proporcionais ao WAV aprovado.
- **Busca stock:** busca imagens/vídeos gratuitos (Pexels, Pixabay vídeo, Wikimedia) via `direct_clip_search`, com licença/autor gravados por cena e `CREDITS.md` gerado.
- **WAV aprovado (somente leitura):** `D:\Youtube-Automacao\Audios\audio_final_documentario.wav`
  - sha256 `82808d024b02236e0eff891ff74d6d05879715e3e1bc13c2f667869dbe80692c`
  - 181 278 bytes
  - Este arquivo e o perfil de mixagem aprovado **não podem ser alterados** pelo Studio.

Arquitetura de referência: `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`.

---

## 2. Funcionalidades concluídas

### Etapa 3 (checkpoint `ff9dbd2`)

| Área | Status |
|------|--------|
| Janela principal: tema, duração planejada, preferências preparatórias | concluído |
| Narração Kokoro (vozes `af_heart`, `am_echo`, `am_michael`) | concluído |
| Música local por catálogo + humor | concluído |
| Mixagem aprovada (voz +3 dB · duck −35 dB · master +3 dB · teto −1 dBFS) | concluído — **inalterada** |
| Timeline não destrutiva (model `lib/studio_timeline.py`) | concluído |
| Editor de timeline (`lib/studio_timeline_ui.py`) | concluído |
| Exportador MP4 verificado (`tools/video/studio_export.py`) | concluído |
| QA Stage 3 reprodutível | concluído |

### Etapa 4 (commit `cc5639f`)

| Área | Arquivo | Status |
|------|---------|--------|
| Formato de plano `scenes.json` (carga, validação atômica, conversão para `TimelineItem`, round-trip de exportação) | `lib/studio_scenes.py` | **novo** |
| Schema JSON do contrato `version: "1.0"` | `schemas/studio/scenes.schema.json` | **novo** |
| Botões **Importar plano** / **Exportar plano** na timeline | `lib/studio_timeline_ui.py` | alterado |
| Confirmação antes de substituir a timeline | `lib/studio_timeline_ui.py` | alterado |
| Troca de WAV do plano só após confirmação explícita (WAV aprovado protegido) | `lib/studio_timeline_ui.py` | alterado |
| *Ajustar ao WAV* automático após import bem-sucedido | `lib/studio_timeline_ui.py` | alterado |
| Menção a `scenes.json` na ajuda dos 3 modos | `openmontage_studio.py` | alterado |
| Unitários do formato de plano (34 testes) | `tests/unit/test_studio_scenes.py` | **novo** |
| Testes de UI de import/export/round-trip/WAV (6 novos) | `tests/test_studio_timeline_ui.py` | alterado |
| QA Stage 4 ponta a ponta | `scripts/validate_studio_stage4_scenes_import.py` | **novo** |

### Etapa 5 (commit `12fe739`)

| Área | Arquivo | Status |
|------|---------|--------|
| Scene sem `media` é planejamento (nunca inventa mídia) | `lib/studio_scenes.py` | alterado |
| Campo `narration` por cena (ajuda de planejamento) | `lib/studio_scenes.py` | alterado |
| `save_plan` / `planning_count` / `scenes_to_items(include_planning=False)` | `lib/studio_scenes.py` | alterado |
| Schema: `media` opcional, `narration`, `metadata` livre | `schemas/studio/scenes.schema.json` | alterado |
| Gerador local de plano (parágrafo → cena, proporção por palavras, piso 2 s, drift zero) | `lib/studio_scene_generator.py` | **novo** |
| Botão **Gerar Plano…** (diálogo com texto da narração) | `lib/studio_timeline_ui.py` | alterado |
| Import de plano só de planejamento não toca a timeline (mostra erro amigável) | `lib/studio_timeline_ui.py` | alterado |
| Unitários do gerador + suporte a planejamento no formato | `tests/unit/test_studio_scene_generator.py`, `tests/unit/test_studio_scenes.py` | **novo/alterado** |
| Testes de UI do Gerar Plano + import de plano só de planejamento | `tests/test_studio_timeline_ui.py` | alterado |

### Garantias verificadas (QA Stage 5)

- Gerador **não inventa caminhos de mídia** — todas as cenas saem com `media` ausente e `note` de planejamento.
- Durações somam **exatamente** `audio_frames(wav_duration)` (sem drift).
- Piso de **2 s** por cena; se o WAV for curto demais para tantas cenas, o gerador rejeita com mensagem clara.
- Importar plano só de planejamento → erro amigável, **timeline intocada**.
- Round-trip de plano com cenas de planejamento: salva sem `media`, recarrega com `planning_count` correto, `scenes_to_items` retorna só as cenas com mídia.
- Fingerprints do WAV aprovado inalterados (sha256 idêntico antes/depois).

### Etapa 6 (sem commit — alterações pendentes)

Busca automática de imagens/vídeos gratuitos (Pexels, Pixabay vídeo, Wikimedia Commons) com licença/autor gravados na cena, reutilizando `stock_sources` e `direct_clip_search` existentes — nenhum cliente HTTP novo.

| Área | Arquivo | Status |
|------|---------|--------|
| Campos de proveniência por cena (`source`, `source_id`, `source_url`, `creator`, `license`) | `lib/studio_scenes.py` | alterado |
| Schema: propriedades de proveniência opcionais | `schemas/studio/scenes.schema.json` | alterado |
| Helper fino de busca (input do tool, filtro de fontes, `scene_with_clip`, `write_credits`) | `lib/studio_stock_search.py` | **novo** |
| Botão **Buscar mídia stock…** (diálogo com cena, termo, tipo, nº) | `lib/studio_timeline_ui.py` | alterado |
| Worker de busca com cancelamento via `cancel_event` + evento `stock_results` | `lib/studio_timeline_ui.py` | alterado |
| Janela de resultados (árvore com arquivo/fonte/autor/licença) | `lib/studio_timeline_ui.py` | alterado |
| **Usar nesta cena** — preenche `media` + proveniência, salva plano, gera `CREDITS.md` | `lib/studio_timeline_ui.py` | alterado |
| **Adicionar à timeline** — caminho direto via `add_paths` | `lib/studio_timeline_ui.py` | alterado |
| Estado `current_plan` / `current_plan_path` no editor | `lib/studio_timeline_ui.py` | alterado |
| `install_instructions` do `direct_clip_search` menciona `PIXABAY_API_KEY` | `tools/video/direct_clip_search.py` | alterado (1 linha) |
| Unitários do contrato de proveniência (4 novos) | `tests/unit/test_studio_scenes.py` | alterado |
| Unitários do helper stock | `tests/unit/test_studio_stock_search.py` | **novo** |
| Testes de UI do fluxo stock (9 novos) | `tests/test_studio_timeline_ui.py` | alterado |
| QA Stage 6 ponta a ponta (offline, mock de transporte) | `scripts/validate_studio_stage6_stock.py` | **novo** |

### Garantias verificadas (QA Stage 6)

- Busca roda via `DirectClipSearch` (fan-out, download, thumbnails, proveniência, timeout) — **nenhum cliente HTTP novo**.
- Fontes expostas: `pexels`, `pixabay_video`, `wikimedia` (filtradas por `available_sources()`); se nenhuma disponível, diálogo com instruções de instalação.
- Proveniência (`source`, `source_id`, `source_url`, `creator`, `license`) gravada por cena; round-trip do `scenes.json` preserva os campos.
- `CREDITS.md` gerado ao lado do plano a cada associação, alinhado a `stock-sourcing-usage.md`.
- Downloads em subpasta `stock/` do projeto — nunca sobrescrevem mídia existente nem o WAV.
- Cancelamento via `cancel_event` descarta os resultados quando a chamada de busca retorna; `DirectClipSearch.execute()` não recebe esse evento, portanto a requisição em andamento não é interrompida imediatamente. Timeout parcial preserva os candidatos já baixados.
- **WAV aprovado inalterado** (sha256 idêntico antes/depois de busca + associação + export).
- Exportador `studio_export.py` intocado (guardas de sobrescrita e fingerprint preservados).
- Compatibilidade Etapa 3–5: planos sem proveniência continuam válidos; 16 testes de UI existentes + 89 testes Studio verdes.

### Etapa 7 (este checkpoint)

Cenas de teste HyperFrames integradas à montagem local: geração de uma cena animada renderizada como MP4 silencioso 1920×1080 · 30 fps, com associação ao plano `scenes.json` e à timeline — reutilizando `tools/video/hyperframes_compose.py` existente (nenhum cliente HTTP novo, nenhum renderer novo).

| Área | Arquivo | Status |
|------|---------|--------|
| Helper fino (status do runtime, `edit_decisions` de teste, render com nomes únicos, verificação ffprobe do contrato 1080p30 silencioso) | `lib/studio_hyperframes.py` | **novo** |
| Botão **Cena HyperFrames…** + diálogo (texto, subtítulo, duração ≤ 30 s, cena de destino, adicionar à timeline) | `lib/studio_timeline_ui.py` | alterado |
| Worker com progresso por fase e falhas como evento `hyperframes_scene` (nunca derruba o Tk) | `lib/studio_timeline_ui.py` | alterado |
| Associação: `media` + proveniência `source=hyperframes` (criador + licença local), identidade da cena preservada na timeline | `lib/studio_timeline_ui.py` | alterado |
| Texto de ajuda dos modos menciona cenas HyperFrames | `openmontage_studio.py` | alterado (1 linha) |
| Unitários do helper (28 testes) | `tests/unit/test_studio_hyperframes.py` | **novo** |
| Testes de UI do fluxo (8 novos; 49 no total) | `tests/test_studio_timeline_ui.py` | alterado |
| QA Stage 7 ponta a ponta (render real via UI + export + WAV) | `scripts/validate_studio_stage7_hyperframes.py` | **novo** |

### Garantias verificadas (QA Stage 7)

- Render real disparado pelo botão da UI: scaffold → lint → validate → render via `hyperframes_compose` (CLI `npx hyperframes` 0.8.155, Node 24).
- MP4 da cena: **1920×1080, 30 fps, H.264, sem trilha de áudio** (ffprobe), 3,0 s.
- Associação grava `media` + proveniência (`source: hyperframes`, criador, licença local) somente na cena escolhida; a outra cena de planejamento permanece sem mídia.
- Identidade da cena (`_timeline_scene_ids`) mantida após associação + ajuste ao WAV + export.
- Compatibilidade: plano estilo Etapa 5 (sem proveniência) carrega; planos stock da Etapa 6 continuam válidos.
- Saídas nunca sobrescrevem: nomes com timestamp + sufixo `-N` (MP4 e workspace).
- Dependências ausentes (Node/npx/FFmpeg/npm) viram erro amigável com instruções, sem derrubar o Studio; exceções do tool viram resumo `ok=False`.
- Export curta com WAV aprovado: 114 quadros, H.264/AAC, decodificação integral; WAV sha256 `82808d0…` inalterado.

Limitações conhecidas da Etapa 7:

- O `cancel_event` só descarta o resultado quando a chamada do CLI retorna — um render em andamento não é interrompido imediatamente (mesma limitação da busca stock).
- A barra de progresso salta por fase (dependências → render → verificação), pois `hyperframes_compose.execute()` roda as 4 fases em uma chamada.
- A cena de teste é um cartão de texto animado; blocos do registry e composições ricas ficam para uma próxima etapa.
- A primeira chamada paga ~10 s extras na sonda `npx hyperframes doctor` (cacheada por processo).
- Cenas HyperFrames entram no `CREDITS.md` como proveniência local (sem atribuição externa exigida).

### Etapa 8 (este checkpoint)

Motor de animação Stickman: personagens articulados em SVG animados por GSAP sobre a infraestrutura HyperFrames da Etapa 7 — personagens/cenários consistentes por preset, ações compostas em beats temporizados, demo 20 s renderizada como MP4 silencioso 1920×1080 · 30 fps, com associação ao plano `scenes.json` e à timeline.

| Área | Arquivo | Status |
|------|---------|--------|
| Motor: `validate_spec`, `build_spec` (presets + escala de beats), `build_timeline_js`, `render_composition_html`, `render_stickman_scene` (via `render_existing`), geometria do rig (viewBox 1920×1080, pivôs, wrappers estáticos), validação de ações/cenários, `preset_default_duration` | `lib/studio_stickman.py` | **novo** |
| 11 ações: `entrar, caminhar, correr, parar, sentar, levantar, digitar, apontar, gesto, comemorar, pensar, repouso` | `lib/studio_stickman.py` | **novo** |
| 2 personagens (`heroi`, `guia`), 4 cenários (`escritorio`, `rua`, `casa`, `abstrato`), 4 presets (`demonstracao_escritorio` 20 s, `caminhar_rua` 15 s, `pausa_casa` 15 s, `gestos_abstratos` 12 s) | `lib/studio_stickman.py` | **novo** |
| Botão **Cena Stickman…** + diálogo (preset, personagem, duração sincronizada ao preset, checkbox timeline, cena de destino) | `lib/studio_timeline_ui.py` | alterado |
| Worker com progresso por fase e falhas como evento `stickman_scene` (nunca derruba o Tk); validação do spec antes do trabalho | `lib/studio_timeline_ui.py` | alterado |
| Associação: `media` + proveniência `source=stickman` (criador + licença local), identidade da cena preservada na timeline | `lib/studio_timeline_ui.py` | alterado |
| Texto de ajuda dos modos menciona cenas Stickman | `openmontage_studio.py` | alterado (1 linha) |
| Unitários do motor (25 testes) | `tests/unit/test_studio_stickman.py` | **novo** |
| Testes de UI do fluxo (9 novos; 58 no total) | `tests/test_studio_timeline_ui.py` | alterado |
| QA Stage 8 ponta a ponta (render real via UI + spec sidecar + export + WAV) | `scripts/validate_studio_stage8_stickman.py` | **novo** |

### Garantias verificadas (QA Stage 8)

- Render real disparado pelo botão da UI: diálogo → worker → `render_existing` (CLI `npx hyperframes` 0.8.156, Node 24) → MP4 1920×1080, 30 fps, H.264, silencioso, 20,0 s.
- Demo executou a sequência completa: **caminhar → sentar → digitar → comemorar → repouso** (frames extraídos e verificados visualmente; correção `_rest_pose` garante pose sentada no final).
- Spec estruturado gravado como `spec.json` ao lado do workspace (preset, personagem, cenário, beats com ações e tempos).
- Associação grava `media` + proveniência (`source: stickman`, criador, licença local) somente na cena escolhida; a outra cena de planejamento permanece sem mídia.
- Identidade da cena (`_timeline_scene_ids`) mantida após associação + ajuste ao WAV + export.
- Saídas nunca sobrescrevem: nomes com timestamp (MP4, workspace, spec).
- Falhas nunca lançam do render (resumo `ok=False` + `error`); `ValueError` só na validação do spec (mostrado antes do trabalho).
- Compatibilidade: planos das Etapas 5–7 (sem proveniência ou com proveniência stock/hyperframes) continuam válidos; `scenes.schema.json` intocado.
- Determinismo: `gsap.timeline({paused:true})` síncrono, sem `Date.now()`/`Math.random()`/rede/loops infinitos em runtime; chave `window.__timelines["stickman"]`.
- Export curta com WAV aprovado: 114 quadros, H.264/AAC, decodificação integral; WAV sha256 `82808d0…` inalterado.

Limitações conhecidas da Etapa 8:

- O `cancel_event` só descarta o resultado quando o CLI retorna (mesma limitação das Etapas 6–7).
- Progresso por fases (dependências → render → verificação), pois `render_existing` roda em uma chamada.
- Lint avisa `nested_structure_needs_subcomposition` (warning benigno, mesmo da Etapa 7).
- O rig usa wrappers estáticos para membros (GSAP anima rotações dos pivôs); expressões faciais e fala lip-sync ficam para uma próxima etapa.
- Cenas Stickman entram no `CREDITS.md` como proveniência local (sem atribuição externa exigida).

---

## 3. Testes

Executar na raiz do repositório:

```bash
# Unitários + UI + exportação do Studio (inclui 28 HyperFrames + 35 Stickman)
.venv/Scripts/python.exe -m pytest tests/unit/test_studio_scenes.py tests/unit/test_studio_scene_generator.py tests/unit/test_studio_stock_search.py tests/unit/test_studio_hyperframes.py tests/unit/test_studio_stickman.py tests/test_studio_timeline_ui.py tests/test_studio_timeline.py tests/test_openmontage_studio.py tests/tools/test_studio_export.py tests/tools/test_studio_export_availability.py -q

# Regressão dos adaptadores stock + direct_clip_search
.venv/Scripts/python.exe -m pytest tests/tools/test_stock_source_adapters.py tests/tools/test_documentary_governance.py -q

# QA local Stage 3 (regressão do fluxo manual + WAV aprovado)
.venv/Scripts/python.exe scripts/validate_studio_stage3.py

# QA local Stage 4 (scenes.json + exportação + integridade do WAV)
.venv/Scripts/python.exe scripts/validate_studio_stage4_scenes_import.py

# QA local Stage 6 (busca stock mockada + associação + CREDITS + WAV)
.venv/Scripts/python.exe scripts/validate_studio_stage6_stock.py

# QA local Stage 7 (render HyperFrames real via UI + associação + export + WAV)
.venv/Scripts/python.exe scripts/validate_studio_stage7_hyperframes.py

# QA local Stage 8 (render Stickman real via UI + spec sidecar + export + WAV)
.venv/Scripts/python.exe scripts/validate_studio_stage8_stickman.py
```

Resultado da última execução (2026-10-14, Etapa 8):

- pytest Studio (suíte canônica): **228 passed** em 49,28 s (unit + UI + timeline + app + export, incluindo HyperFrames e Stickman).
- pytest Stock + governança: **46 passed, 3 xfailed** em 37,06 s. Os três xfails já existiam e tratam da propagação de erros de transporte em `archive_org`, `wikimedia` e `pond5_pd`.
- QA Stage 3: **passed** (WAV aprovado intacto, 114 frames, H.264/AAC)
- QA Stage 4: **passed** (import atômico, round-trip, WAV swap declined, full decode)
- QA Stage 6: **passed** (busca mockada, seleção do segundo clipe na janela Tk real, associação somente à `cena-02`, proveniência, CREDITS.md, export verificado, WAV inalterado)
- QA Stage 7: **passed** (render real 1080p30 silencioso via diálogo da UI, associação com proveniência, timeline com identidade da cena, export 114 frames, WAV inalterado)
- QA Stage 8: **passed** (render real Stickman 20 s via diálogo da UI, spec sidecar com a sequência `caminhar→sentar→digitar→comemorar→repouso`, associação com proveniência, evidência visual `evidence-typing.png`, export 114 frames, WAV inalterado)

Os scripts QA criam diretórios únicos em `projects/openmontage-studio/` (gitignored) e não usam APIs pagas.

---

## 4. Pendências (fora do escopo das Etapas 6–8)

1. ~~**Gerador local de `scenes.json` a partir do texto da narração**~~ — concluído na Etapa 5.
2. ~~**Resolução de mídia por palavras-chave**~~ — parcialmente concluído na Etapa 6 (busca stock); resolução em pastas locais continua manual.
3. **Ponte com o pipeline `documentary-montage`** — converter `scene_plan`/`asset_manifest` do agente em `scenes.json` para revisão/export no Studio.
4. **Legendas** (SRT / queimadas) — UI ainda marca como “não integrado”.
5. **Narração em português** — Kokoro desta instalação gera só inglês; PT/DE/ES são preferências preparatórias.
6. **Alvo rígido de duração** — hoje a duração final sempre segue o WAV de narração.
7. **Edição automática de vídeo bruto** — modo “Editar vídeo” só registra o arquivo; não analisa nem corta.
8. **Roteiro automático** — ainda manual.
9. **Escala longa (40+ cenas)** — o exportador faz 1 passe FFmpeg por corpo + 1 por transição; aceitável hoje, otimização de passes é futura.
10. **Busca stock em lote para todas as cenas de planejamento** — hoje é cena a cena; batch automático é futuro.
11. **Filtro de licença non-free do Wikimedia** — o helper grava a licença mas não filtra automaticamente itens "non-free"/"fair use".
12. **Cancelamento imediato do render HyperFrames/Stickman** — o `cancel_event` só descarta o resultado após o CLI retornar; interromper o processo em andamento é futuro.
13. **Cenas HyperFrames mais ricas** — usar blocos do registry / composições além do cartão de texto de teste; permitir playground/narration no diálogo.
14. **Presets Stickman adicionais e expressões** — mais roupas/props, expressões faciais, fala lip-sync, mais cenários (ex.: praça, cozinha detalhada).
15. **Compose de múltiplas cenas Stickman** — hoje o diálogo gera uma cena por vez; composição de várias cenas Stickman em sequência numa única renderização é futura.

---

## 5. Próximo passo recomendado

Implementar a **busca stock em lote** para todas as cenas de planejamento de um plano, e o **filtro de licença** non-free do Wikimedia:

- Botão "Buscar para todas as cenas" itera as cenas com `media` ausente, usa `narration`/`note` como query, e aplica o resultado automaticamente (com revisão manual opcional).
- Filtro: descartar candidatos do Wikimedia com licença contendo "non-free" ou "fair use" antes de sugerir.
- Critério de aceite: gerar plano → buscar lote → associar → exportar, tudo offline-testável com mocks, WAV aprovado intacto.

Alternativas: **presets Stickman adicionais** (expressões, lip-sync, novos cenários — pendência 14), **compose de várias cenas Stickman** numa única renderização (pendência 15) ou a **ponte `scene_plan → scenes.json`** (padrão `audio_mix_plan.py`), que converte o `asset_manifest` do pipeline em cenas com proveniência já preenchida — reutiliza os campos de proveniência da Etapa 6.

---

## 6. Regras permanentes (não negociáveis)

- **Não alterar** `D:\Youtube-Automacao\Audios\audio_final_documentario.wav` nem o perfil de mix aprovado.
- Exportação nunca sobrescreve mídia original, WAV existente nem MP4 existente.
- Importação de plano nunca troca o WAV ativo sem confirmação explícita.
- Stock downloads nunca escrevem no WAV aprovado nem sobrescrevem mídia existente (subpasta `stock/` dedicada).
- Preferências de idioma/legenda/estilo permanecem preparatórias até integração real.
- Nenhum commit deve incluir mídias, WAVs de teste, `.env`, chaves, `backups/`, `projects/`, `__pycache__` ou históricos de ferramentas (`.aider*`).
- Nenhum cliente HTTP novo — a busca stock reutiliza `stock_sources` e `direct_clip_search`; o render HyperFrames reutiliza `hyperframes_compose` (CLI local `npx hyperframes`).

---

## 7. Mapa de arquivos (Etapas 6–8)

```
lib/studio_hyperframes.py                     # helper HyperFrames (Etapa 7)
lib/studio_stickman.py                        # motor Stickman (novo, Etapa 8)
lib/studio_scenes.py                          # contrato scenes.json (+ proveniência)
lib/studio_stock_search.py                    # helper fino de busca stock
lib/studio_timeline_ui.py                     # UI: stock + HyperFrames + Stickman + CREDITS
lib/studio_scene_generator.py                 # gerador de plano (inalterado)
openmontage_studio.py                         # launcher (ajuda dos modos)
schemas/studio/scenes.schema.json             # schema JSON do plano (+ proveniência)
tools/video/hyperframes_compose.py            # tool HyperFrames (inalterado)
tools/video/direct_clip_search.py             # install_instructions (+ Pixabay)
tools/video/stock_sources/                    # adaptadores (inalterados)
tools/video/studio_export.py                  # exportador (intocado)
tests/unit/test_studio_hyperframes.py         # 28 unitários do helper HyperFrames
tests/unit/test_studio_stickman.py            # 25 unitários do motor Stickman (novo)
tests/unit/test_studio_scenes.py              # 42 unitários do formato
tests/unit/test_studio_stock_search.py        # testes do helper stock
tests/unit/test_studio_scene_generator.py     # unitários do gerador
tests/test_studio_timeline_ui.py              # 58 testes de UI (inclui 8 HyperFrames + 9 Stickman)
tests/tools/test_stock_source_adapters.py     # 35 testes dos adaptadores
scripts/validate_studio_stage8_stickman.py    # QA ponta a ponta Stickman (novo)
scripts/validate_studio_stage7_hyperframes.py # QA ponta a ponta HyperFrames
scripts/validate_studio_stage6_stock.py       # QA ponta a ponta stock
scripts/validate_studio_stage4_scenes_import.py  # QA de regressão
scripts/validate_studio_stage3.py             # QA de regressão
```

Relatórios de QA (não versionados): `projects/openmontage-studio/qa-stage3-*/validation.json`, `qa-stage4-*/validation.json`, `qa-stage6-*/validation.json`, `qa-stage7-*/validation.json`, `qa-stage8-*/validation.json`.

---

## 8. Retomada de 2026-10-14 — seleção e associação stock

### Estado recebido e preservação

- Branch: `openmontage-studio-etapa4`; HEAD: `12fe739` (Etapa 5).
- Recebido com 12 arquivos rastreados modificados, além de arquivos não rastreados da Etapa 6, backups, históricos e mídias locais. Índice vazio; nenhum commit ou staging realizado nesta retomada.
- As mudanças pendentes atribuídas ao OpenCode foram mantidas. Configuração, launcher/app, contrato/schema de cenas, Remotion, diretores do pipeline e adaptadores não foram reescritos nesta correção.
- Comparação por SHA-256, tamanho e mtime confirmou o WAV aprovado, **23 arquivos em `backups/`**, `config.yaml.backup`, o exportador e os arquivos pendentes fora da correção intactos.
- WAV aprovado: `82808d024b02236e0eff891ff74d6d05879715e3e1bc13c2f667869dbe80692c`, 181278 bytes. Perfil de mixagem preservado.

### Defeito reproduzido e correções

1. A árvore de resultados usava IDs automáticos (`I001`, etc.), mas selecionava `"0"` e convertia a seleção com `int()`. Dois testes novos com os botões reais reproduziram `TclError: Item 0 not found`. A janela agora usa o ID devolvido por `Treeview.insert()` para localizar o clipe correto, tanto em **Usar nesta cena** quanto em **Adicionar à timeline**.
2. A cena sugerida deixa de ser obtida pela posição bruta na lista do plano. A UI guarda o ID da cena de origem dos itens importados e mantém esse vínculo após ajuste ao WAV, edição, reordenação e remoção, inclusive quando duas cenas compartilham o mesmo vídeo. Itens adicionados manualmente não recebem um vínculo inventado.
3. Trocar a cena no diálogo atualiza o termo de busca com sua narração/nota. Cancelar a substituição da timeline mantém o plano ativo e o WAV anteriores.
4. Associação e adição validam existência e extensão da mídia. Se o arquivo sumir ou o salvamento falhar, a janela de resultados permanece aberta para tentar novamente; o estado em memória não é atualizado antes de salvar.
5. O helper preserva candidatos e erros retornados por timeout. Falhas sem candidatos aparecem como erro de busca; falha ao gravar `CREDITS.md` é comunicada, sem anunciar créditos salvos.
6. Gerar outro plano conserva `plans/scenes.json` quando já existe, usando um nome com timestamp para o novo plano.
7. O QA Stage 6 não substitui mais `_show_stock_results` por mock: abre a janela real, seleciona o segundo resultado e aciona o botão de associação para `cena-02`, verificando que `cena-01` continua sem mídia antes da importação e exportação.

Arquivos de implementação/testes alterados nesta retomada: `lib/studio_timeline_ui.py`, `lib/studio_stock_search.py`, `tests/test_studio_timeline_ui.py`, `tests/unit/test_studio_stock_search.py`, `scripts/validate_studio_stage6_stock.py`. Documentação: este `HANDOFF.md` e o registro solicitado em `HANDOOF.md`.

### Evidências

- Antes da correção: suíte relacionada com **188 passed, 3 xfailed**; testes novos de seleção falhavam nos dois botões.
- Após a correção: **204 passed, 3 xfailed**; suíte focada UI/helper com **59 passed**; `git diff --check` sem erros.
- QAs 3, 4 e 6 aprovados: MP4 1920×1080, 30 fps, H.264/AAC, 114 quadros, áudio completo de 3,775 s e decodificação integral sem erro.
- Relatórios: `projects/openmontage-studio/qa-stage3-20261014-004900-504594/validation.json`, `qa-stage4-20261014-004901-603283/validation.json` e `qa-stage6-20261014-004900-955335/validation.json` sob o mesmo diretório pai.
- Auditoria de preservação: `projects/openmontage-studio/qa-stage6-repair-20261014/protected-before.json` e `protected-after.json`.

Busca externa foi simulada; não houve chamada paga nem validação ao vivo dos provedores. A associação continua salvando o plano e os créditos; para atualizar a montagem, use **Importar plano**. Busca em lote, filtro non-free do Wikimedia e interrupção imediata de requisições permanecem pendentes.

---

## 9. Retomada de 2026-10-14 — Etapa 7 (HyperFrames no Studio)

### Estado recebido e preservação

- Branch: `openmontage-studio-etapa4`; HEAD: `12fe739`; índice vazio; nenhum commit ou staging nesta retomada (exigência do usuário).
- Preservados sem alteração: `config.yaml`, `openmontage_studio.py` (exceto 1 linha de ajuda), `lib/studio_scenes.py`, `remotion-composer/package-lock.json`, `schemas/studio/scenes.schema.json` (CRLF), skills dos diretores e `tools/video/direct_clip_search.py` (todas as alterações pendentes do Codex/Etapa 6 mantidas).
- Compatibilidade avaliada antes de codar: `hyperframes doctor` ok (Node 24, ffmpeg 9.0.2); render smoke manual validou o contrato 1080p30 silencioso em ~59 s.

### Implementação

1. `lib/studio_hyperframes.py` (novo): `hyperframes_status`/`format_unavailable_error`, `validate_duration` (1/30–30 s; `ValueError` com mensagem amigável), `build_test_edit_decisions`, `unique_path`/`unique_dir` (nunca sobrescrever), `probe_scene` (ffprobe: codecs, fps, silêncio), `render_test_scene` (uma chamada `HyperFramesCompose().execute({"operation": "render", ...})` com resumo `ok=False` em falha; cancelamento só após o CLI retornar).
2. `lib/studio_timeline_ui.py`: botão **Cena HyperFrames…** no modo Criar; diálogo com texto (obrigatório), subtítulo, duração (default 3 s, aceita vírgula), checkbox "Adicionar à timeline" e combobox de cena de destino (default "(não associar)" quando a cena escolhida já tem mídia); worker com progresso por fase (0.03/0.10/0.9/1.0) e eventos `hyperframes_scene`; `_finish_hyperframes_scene` associa via `_apply_clip_to_scene` com proveniência `source="hyperframes"`, `creator="OpenMontage Studio (HyperFrames)"`, `license="Gerado localmente (HTML/CSS/GSAP); sem licença externa."` e adiciona `TimelineItem` com a identidade da cena em `_timeline_scene_ids`.
3. `openmontage_studio.py`: texto de ajuda do modo Criar menciona cenas HyperFrames (1 linha; nenhum teste asserta o texto).
4. Testes: 28 unitários do helper + 8 de UI (diálogo, validação, falha, associação+timeline, timeline-only, plano-only, cancel).
5. `scripts/validate_studio_stage7_hyperframes.py`: QA real via botão/dialogo Tk → render (~1 min) → associação → ajuste ao WAV → export → verificação do contrato → fingerprint do WAV. Sai com JSON de "skipped" (sem falhar) quando o runtime HyperFrames não existe na máquina.

### Evidências

- pytest Studio: **195 passed**; adaptadores + governança: **46 passed, 3 xfailed**.
- QAs 3, 4, 6 e **7 passed**; QA 7: render `cena-hyperframes-*.mp4` 1920×1080/30 fps/H.264/silencioso 3,0 s, associado a `cena-01` com proveniência, `cena-02` intacta, export 114 quadros H.264/AAC, WAV sha256 `82808d0…` inalterado.
- Relatórios: `projects/openmontage-studio/qa-stage7-20261014-012439-900362/validation.json` (e `qa-stage3-*`, `qa-stage4-*`, `qa-stage6-*` da mesma execução).
- `git diff --check` limpo (apenas aviso de CRLF pré-existente em `scenes.schema.json`); nenhum staging, nenhum commit.

### Limitações registradas

Cancelamento não interrompe o render em andamento; progresso por fases (uma chamada ao tool); cena de teste é cartão de texto (registry blocks futuros); ~10 s extras no primeiro `doctor` por processo; cenas HyperFrames aparecem em `CREDITS.md` como proveniência local.

---

## 10. Retomada de 2026-10-14 — Etapa 8 (Stickman no Studio)

### Estado recebido e preservação

- Branch: `openmontage-studio-etapa4`; HEAD: `12fe739`; índice vazio; nenhum commit ou staging nesta retomada (exigência do usuário).
- Preservados sem alteração: `config.yaml`, `lib/studio_scenes.py`, `remotion-composer/package-lock.json`, `schemas/studio/scenes.schema.json` (CRLF), skills dos diretores e `tools/video/direct_clip_search.py` (todas as alterações pendentes do Codex/Etapa 6 mantidas).
- Compatibilidade avaliada antes de codar: `hyperframes doctor` ok (Node 24, ffmpeg 9.0.2); infraestrutura da Etapa 7 (`lib/studio_hyperframes.py`) reutilizada como base (status, probe, unique paths, validate_duration).

### Implementação

1. `lib/studio_stickman.py` (novo): `validate_spec` (presets, personagens, cenários, ações, beats ordenados/dentro da duração, `to_x` em `caminhar`/`correr`, `sentar`/`levantar` só em cenários com cadeira, `digitar` só em escritório, max 30 s); `build_spec` (presets com duração default, escala proporcional dos beats para a duração escolhida); `preset_default_duration`; `_scenario_svg`/`_character_svg` (SVG por cenário/personagem); `build_timeline_js` (uma timeline `paused:true` por action-to-cue, com `yoyo`/`repeat` limitados, sem loops infinitos); `render_composition_html` (contrato HyperFrames: root `data-composition-id="stickman"`, CDN GSAP, `window.__timelines["stickman"]`); `render_stickman_scene` (workspace autoral com `index.html` + `spec.json` → `HyperFramesCompose().execute({"operation": "render_existing", ..., "skip_contrast": True})` → `probe_scene`; falhas viram resumo `ok=False`).
2. `lib/studio_timeline_ui.py`: botão **Cena Stickman…** no modo Criar; diálogo com combobox de preset (default `demonstracao_escritorio`), personagem (default `heroi`), duração sincronizada ao preset via `preset_default_duration`, checkbox "Adicionar à timeline" e combobox de cena de destino; validação do spec (`validate_stickman_spec`) antes de iniciar o worker; worker com progresso por fase (0.05/0.15/0.9/1.0) e eventos `stickman_scene`; `_finish_stickman_scene` associa via `_apply_clip_to_scene` com proveniência `source="stickman"`, `creator="OpenMontage Studio (Stickman)"`, `license="Gerado localmente (SVG/GSAP); sem licença externa."` e adiciona `TimelineItem` com a identidade da cena em `_timeline_scene_ids`.
3. `openmontage_studio.py`: texto de ajuda do modo Criar menciona cenas Stickman (1 linha).
4. Rig: viewBox 1920×1080 (ground y=900, hip em pé 790, sentado 845); torso/head/membros com pivôs via `transform-origin` e `transform-box: fill-box`; wrappers estáticos `<g transform="translate(...)">` nunca animados; forward = -90 (rotação negativa = frente/direita).
5. Testes: 25 unitários do motor + 9 de UI (diálogo defaults, duração por preset, validação do spec, falha, associação+timeline, timeline-only, cancel).
6. `scripts/validate_studio_stage8_stickman.py`: QA real via botão/dialogo Tk → render (~2–3 min) → associação → spec sidecar → frame de evidência → ajuste ao WAV → export → verificação do contrato → fingerprint do WAV. Sai com JSON de "skipped" (sem falhar) quando o runtime HyperFrames não existe na máquina.

### Evidências

- pytest Studio (suíte canônica): **228 passed**; Stock + governança: **46 passed, 3 xfailed**.
- QAs 3, 4, 6, 7 e **8 passed**; QA 8: render `cena-stickman-*.mp4` 1920×1080/30 fps/H.264/silencioso 20,0 s, spec com sequência `caminhar→sentar→digitar→comemorar→repouso`, associado a `cena-01` com proveniência, `cena-02` intacta, export 114 quadros H.264/AAC, WAV sha256 `82808d0…` inalterado.
- Frames extraídos e verificados visualmente durante o smoke: caminhar, sentado ao computador, digitar, comemorar (pulando), final sentado (após correção `_rest_pose`).
- Relatórios: `projects/openmontage-studio/qa-stage8-20261014-025336-680279/validation.json` (e `qa-stage3-*`, `qa-stage4-*`, `qa-stage6-*`, `qa-stage7-*` da mesma execução).
- `git diff --check` limpo; nenhum staging, nenhum commit.

### Limitações registradas

Cancelamento não interrompe o render em andamento; progresso por fases; lint warning benigno `nested_structure_needs_subcomposition` (mesmo da Etapa 7); rig sem expressões faciais/fala lip-sync; uma cena Stickman por vez (compose multi-cena futuro); cenas Stickman aparecem em `CREDITS.md` como proveniência local.

**Etapa 8 encerrada — não avançar para a Etapa 9 sem aprovação do usuário.**

## 11. Retomada de 2026-10-14 — Etapa 8.1 (correções do rig Stickman)

### Escopo

`ETAPA8_1_INSTRUCOES.txt`: corrigir os bugs visuais do Stickman (hierarquia de articulações, alinhamento sentar/mesa/cadeira, extremidades destacadas, transições bruscas, ordem de camadas), criar testes que validem posições de articulações e quadros intermediários, preservar todo o trabalho das Etapas 3–8, rodar testes/QAs — sem avançar para a Etapa 9.

### Bugs confirmados nos frames da Etapa 8 e causa raiz

1. **Pivô do tronco errado**: o grupo do torso usava `transform-origin: 50% 100%` com fill-box que incluía a cabeça e os braços — a bbox ia das mãos ao topo da cabeça, então o "quadril" do pivot caía na altura das mãos; o torso atravessava a mesa e o corpo ficava deitado ao sentar.
2. **Sinais de rotação invertidos nas poses sentadas**: convenção real do rig (validada por FK e pelos frames): **rotação negativa = frente/direita (para +x)**, positiva = trás. A pose sentada usava `legR1/armR1` positivos, apontando pernas e braços para trás através da cadeira.
3. **Braços destacados na comemoração**: pivôs instáveis no fill-box deslocavam o grupo `#sm-upper` quando os braços giravam.
4. **Transições bruscas**: caminhar/correr terminavam sem settle para a pose de repouso.

### Correções aplicadas (apenas `lib/studio_stickman.py` + testes)

- **Hierarquia**: torso virou um retângulo único (classe `sm-torso-rot`, pivot `50% 100%` = quadril real); cabeça + braços migraram para o grupo irmão `#sm-upper` (classe `sm-upper`) com âncora invisível `<rect x="-150" y="-200" width="300" height="270" fill="none"/>` que estabiliza a fill-box (pivot `50% 71.4%`); âncora invisível no head (`50% 96.7%`); mãos `cy=44 r=7`; pés retangulares no fim da canela.
- **Torso-followers**: `_TORSO_FOLLOWERS = ("sm-torso", "sm-upper")` — a rotação do tronco é emitida para ambos; `gsap.set` explícitos de `transformOrigin` no início da timeline (GSAP default é o centro do bbox).
- **Convenção de sinais corrigida**: `_SEATED` com thighs para frente (`legR1: -88`, `legR2: +88` → canela vertical, pé em y≈902 vs chão 900), braços para frente (`armR1: -52`); `digitar` (`armR1: -84`, torso `-6`), `apontar` (`-92`), `gesto` (`-140`), `comemorar` (`armR1: -150`/`armL1: +150`, **sem hops quando sentado**), `pensar` (`-55`/`-118`), correr com torso `-8` (inclinação para frente).
- **Suavização**: caminhar/correr emitem settle para `_IDLE` nos últimos ~0.28 s; joints com `sine.inOut` no walk.

### Testes novos (Etapa 8.1)

`tests/unit/test_studio_stickman.py`: +10 testes (35 total, os 25 originais preservados):

- FK matemático das juntas (`_leg_joints`/`_arm_joints` com a geometria real do SVG: coxa 55, canela+pé 55, braço 42+mão 44): pés sentados tocam o chão (y≈900±10), canelas verticais (ângulo total ≤10°), joelhos à frente do quadril e sob a mesa (x∈[1000,1470], y entre 752 e 868), mãos de digitar à frente do ombro e na altura do teclado (y∈[700,800]).
- Quadros intermediários: tween raiz do caminhar linear 6 s (`ease:"none"`), tween do sentar com duração 1,4 s (não instantâneo), ≥8 poses intermediárias de perna durante o caminhar, ordem sentar→digitar→comemorar na timeline, comemorar sentado sem tweens de salto no root (times <14,4 s).
- Estrutura: `_TORSO_FOLLOWERS == {sm-torso, sm-upper}` e timeline emite rotação `-6.0` para ambos; mãos/pés aninhados nos grupos pai (≤400 chars após o id); head dentro de `#sm-upper` com âncora `fill="none"`.

### Evidências

- Sintaxe `ast.parse` ok; **35 unit Stickman passed**; **57 UI passed**; suíte canônica **229 passed, 1 skipped** (0 falhas).
- Render de verificação 20 s (`demonstracao_escritorio`): `projects/openmontage-studio/stickman-dev/stickman/stickman/cena-stickman-20261014-035533-864738.mp4`; frames extraídos em `projects/openmontage-studio/stickman-dev/v81b/` (t=2 caminhar, 6.5 sentar intermediário, 7.5 sentado, 10 digitar, 15.5 comemorar, 19 repouso) — todos verificados visualmente: cabeça soldada ao tronco, coxas para frente sobre a cadeira, canelas verticais com pés no chão, mãos no teclado, comemoração em V acima da cabeça sem descolar braços.
- QAs re-executados: **3, 4, 6, 7 e 8 passed** (QA 8: novo render real via UI 20 s, `qa-stage8-20261014-040955-769124/`, evidence-typing.png corrigido, WAV sha256 `82808d0…` inalterado).
- `git diff --check` limpo; nenhum staging, nenhum commit; alterações pendentes do Codex/Etapa 6 preservadas.

**Etapa 8.1 encerrada — não avançar para a Etapa 9 sem aprovação do usuário.**
