# RELATÓRIO — Auditoria OpenMontage Etapa 8.2 (OpenCode)

**Data:** 2026-10-14 · **Escopo:** auditoria e diagnóstico (nenhuma alteração de código).
**Base documental:** `AGENT_GUIDE.md` (via `AGENTS.md`), `HANDOFF.md`, `ETAPA8_2_AUDITORIA.txt`, `ETAPA8_1_INSTRUCOES.txt`.
**Estado do repositório:** branch `openmontage-studio-etapa4`, HEAD `12fe739` (Etapa 5); 12 arquivos rastreados modificados + ~30 não rastreados (Etapas 6–8.1) pendentes de commit. Nenhum staging/commit foi feito. WAV aprovado `82808d02…` não foi tocado nesta auditoria.

**Evidência visual analisada:** frames extraídos do render real da Etapa 8.1 em `projects/openmontage-studio/audit-stage8-2-20261014-042920/` (12 frames + contact sheet; fonte `qa-stage8-20261014-040955-769124/stickman/cena-stickman-20261014-040956-182885.mp4`, sha256 `02afcbb7…`, 20,0 s, 1920×1080, 30 fps, H.264 silencioso — HTML idêntico ao motor atual).

**Confirmação independente (2026-10-14):** relatório do OpenCode lido integralmente antes desta retomada. Testadas as afirmações principais contra o manifesto, implementação, HTML/MP4 e frames já gerados; suíte de regressão Studio + stock executada nesta retomada. As correções factuais feitas abaixo substituem conclusões antigas que a inspeção não confirmou. O detalhe e a trilha desta confirmação constam na seção 8.

---

## 1. Inventário de agentes e funcionalidades

### 1.1 Arquitetura orquestrada original (camadas 1–3)

| Camada | Itens |
|---|---|
| Pipelines (`pipeline_defs/`) | 13 manifests: `animated-explainer`, `animation`, `avatar-spokesperson`, `character-animation`, `cinematic`, `clip-factory`, `documentary-montage`, `framework-smoke`, `hybrid`, `localization-dub`, `podcast-repurpose`, `screen-demo`, `talking-head` |
| Diretores (`skills/pipelines/`) | 103 arquivos de diretores em 12 famílias; `documentary-montage` tem 6 diretores próprios (executive-producer, idea, scene, asset, edit, compose), além das meta skills reviewer e checkpoint protocol declaradas no manifesto. Pesquisa, roteiro e proposal não são stages desse pipeline. |
| Meta skills (`skills/meta/`) | 11: onboarding, checkpoint-protocol, reviewer, taste-direction, bespoke-composition, animation-runtime-selector, video-reference-analyst, entre outras |
| Skills criativas (`skills/creative/`) | 30 arquivos, incluindo `video-editing.md`, `stock-sourcing-usage.md`, `ink-theater.md`, `animation-pipeline.md` |
| Layer 3 (`.agents/skills/`) | ~90 skills de fornecedores/tecnologia (GSAP, HyperFrames, Remotion, Seedance, ElevenLabs, character-rigging, svg-character-animation, etc.) |
| Ferramentas (`tools/`) | ~180 módulos Python: TTS (17 provedores), geração de imagem (~25), geração de vídeo (~30), stock/clip search (19 adaptadores + corpus CLIP), análise (transcriber, scene_detect, video_analyzer, frame_sampler, visual_qa…), avatar, character_animation (6 tools), 3D, enhancement, legendas (`subtitle_gen`, `remotion_caption_burn`), mixagem, exportação |
| Infraestrutura | `tools/tool_registry.py` (descoberta + menu de provedores), `lib/checkpoint.py` (checkpoints/gates), `tools/cost_tracker.py`, `lib/pipeline_loader.py`, `lib/source_media_review.py`, `lib/audio_mix_plan.py` |

### 1.2 OpenMontage Studio (Etapas 3–8.1 — o fluxo local do usuário)

| Componente | Arquivo | Estado |
|---|---|---|
| App Tkinter (3 modos: Criar / Editar bruto / Personalizado) | `openmontage_studio.py` | em uso |
| Narração Kokoro (EN, 3 vozes) + música por catálogo local + mixagem aprovada | `tools/audio/kokoro_tts.py`, `tools/audio/audio_mixer.py`, `tools/audio/seletor_musical.py` | funcionando |
| Timeline não destrutiva 30 fps + editor UI | `lib/studio_timeline.py`, `lib/studio_timeline_ui.py` | funcionando |
| Exportador MP4 verificado (nunca sobrescreve, fingerprint WAV) | `tools/video/studio_export.py` | funcionando |
| Formato de plano `scenes.json` (+ schema + proveniência) | `lib/studio_scenes.py`, `schemas/studio/scenes.schema.json` | funcionando |
| Gerador de plano a partir do texto da narração | `lib/studio_scene_generator.py` | funcionando |
| Busca stock (Pexels, Pixabay vídeo, Wikimedia) + `CREDITS.md` | `lib/studio_stock_search.py` → `direct_clip_search` | funcionando (cena a cena); três fontes são suportadas, duas estão disponíveis nesta execução (Pixabay vídeo e Wikimedia) |
| Cena HyperFrames de teste (cartão de texto) | `lib/studio_hyperframes.py` → `hyperframes_compose` | funcionando |
| Motor Stickman (SVG+GSAP) | `lib/studio_stickman.py` | **renderiza e integra, mas com defeitos visuais graves (seção 3)** |
| QA reprodutível | `scripts/validate_studio_stage{3,4,6,7,8}_*.py` | os QAs documentados antes desta retomada estavam aprovados; esta retomada confirma 284 testes passados e 3 xfails (seção 8) |

### 1.3 Componentes de documentário

- **Pipeline `documentary-montage`** (beta): completo e coerente — idea → scene_plan → assets (busca por corpus CLIP com `corpus_builder`/`clip_search` + `direct_clip_search`) → edit → compose (Remotion + end-tag + mixagem obrigatórias). Governança de licenças e proveniência já especificadas nos diretores. **Funciona como fluxo do agente, não no Studio.**
- **Ferramentas de apoio:** `lib/corpus.py`, `lib/clip_embedder.py` (CLIP local), 19 adaptadores stock (`tools/video/stock_sources/`), `tools/analysis/transcriber.py` + `azure_stt`, `tools/audio/music_gen.py` + `music_library.py`.
- **No Studio:** reaproveita `direct_clip_search`; o helper suporta Pexels, Pixabay vídeo e Wikimedia, mas apenas Pixabay vídeo e Wikimedia estavam disponíveis na execução auditada. **Não** há ponte `scene_plan`/`asset_manifest` → `scenes.json` (pendência 3 do HANDOFF, confirmada).

### 1.4 Componentes de edição de vídeo bruto

- **Modo “Editar vídeo bruto” do Studio:** apenas **registra o caminho** do arquivo em modo somente leitura (`openmontage_studio.py:264–270, 351–364` — texto da UI: “não analisa, copia, altera nem exclui”; “análise de conteúdo e edição automática não fazem parte desta etapa”). Confirmada a pendência 7 do HANDOFF.
- **Capacidades originais existentes (não ligadas à UI):** `lib/source_media_review.py` (probe + transcrição + amostras + inferência de usabilidade), `video_analyzer`, `scene_detect`, `silence_cutter`, `auto_reframe`, `video_trimmer`/`video_stitch`, pipelines footage-led `clip-factory`, `hybrid`, `talking-head`.

### 1.5 Legendas e sincronização

- Existe `tools/subtitle/subtitle_gen.py` e `tools/video/remotion_caption_burn.py`; o Studio marca legendas como “não integrado” (pendência 4). Fora do Studio, o pipeline `documentary-montage`/`animated-explainer` já prevê captions via Remotion.

### 1.6 Personagens 2D (relevante para Stickman)

- **Stack original completo:** pipeline `character-animation` (11 diretores) + `tools/character/character_animation.py` com 6 tools (`CharacterSpecGenerator`, `SvgRigBuilder`, `PoseLibraryBuilder`, `ActionTimelineCompiler`, `CharacterRigRenderer`, `CharacterAnimationReviewer`) + skills Layer 2/3 (`character-rigging`, `svg-character-animation`, `pose-library-design`, Ink Theater/Ink Puppet).
- **Studio:** implementou um **rig paralelo e independente** em `lib/studio_stickman.py` (ver duplicação, seção 4).

---

## 2. Classificação geral

| Área | Classificação | Observação |
|---|---|---|
| Narração Kokoro (EN) + mixagem aprovada | **funcional e validado** | fingerprints do WAV verificados em todos os QAs |
| Timeline/export FFmpeg + `scenes.json` + gerador de plano | **funcional e validado** | round-trip e gates de WAV confirmados |
| Busca stock + proveniência + CREDITS | **funcional e validado** (parcial em cobertura) | 2 de 3 fontes suportadas disponíveis na execução; sem lote; sem filtro non-free do Wikimedia |
| Cena HyperFrames (Etapa 7) | **funcional e validado** | cartão de texto apenas; registry blocks não explorados |
| Motor Stickman (Etapa 8/8.1) | **com defeito (visual)** | renderiza, integra e exporta, mas o output tem bugs confirmados (seção 3); os 229 testes não capturam qualidade visual |
| Pipeline `documentary-montage` | **funcional no agente; ausente no Studio** | sem ponte `scene_plan`→`scenes.json`; o compose exige Remotion |
| Modo “Editar vídeo bruto” | **ausente (só registro)** | capacidades de análise/corte existem no repositório mas não estão ligadas |
| Legendas (SRT/queimadas) | **parcial** | ferramentas existem; UI Studio não integra |
| Narração em português | **ausente no Studio** | Kokoro desta instalação só gera EN |
| Roteiro automático no Studio | **ausente** | diretores de script do agente existem e não são usados |
| Expressões/lip-sync/compose multi-cena Stickman | **ausente** | pendências 14–15 do HANDOFF |
| Busca stock em lote + filtro non-free | **ausente** | próximo passo já recomendado no HANDOFF §5 |
| Provedores cloud (pago) | **não auditado nesta etapa** | o fluxo Studio é local-first e não depende deles; menu de provedores não foi sonдado por economia de tokens |

---

## 3. Diagnóstico técnico dos bugs Stickman

O usuário confirmou que o MP4 da Etapa 8.1 continua com: personagem atravessando cadeira/mesa, articulações desconectadas e movimentos artificiais ao sentar e comemorar. Análise dos **frames reais** (contact sheet + zooms de t=7,5 s e t=17,3 s) cruzada com o código de `lib/studio_stickman.py`.

### 3.1 Causas comprovadas (evidência de frame +/ou matemática de código)

**P1 — Cadeira e personagem não têm hierarquia espacial coerente.** Correção à versão anterior: o SVG **tem** assento horizontal (`x=1092..1218`, `y=838..850`). Ele não tem encosto; a coluna do pedestal fica em `x=1090..1102`, enquanto o tronco em repouso sentado ocupa aproximadamente `x=1096..1114`, criando sobreposição. O eixo do quadril (`x=1105`, `y=845`) está na faixa do assento; portanto, não procede dizer que o quadril paira por falta de assento. Os frames mostram uma cadeira esquemática e a personagem desenhada na frente das peças, sem oclusão ou contato articulado com a cadeira. A limitação comprovada é a composição/representação da interação, não a ausência de um assento.

**P2 — O teclado atravessa o pescoço/cabeça da personagem sentada.**
Teclado: `<rect x=1062 y=738 w=150 h=14>` (sobre a mesa, y 738–752). Cabeça sentada: centro (1105, 720), raio 28 → ocupa y 692–748, x 1077–1133 — **sobreposta à faixa do teclado**. No zoom de t=7,5 s a barra escura do teclado corta o pescoço/chin do personagem (cabeça acima, tronco azul abaixo). Causa raiz: `walk_to_x=1105` coloca o quadril **dentro** da faixa x do teclado (1062–1212) e da mesa (x≥1000), e `sit_y=845` deixa a cabeça exatamente na altura do teclado.

**P3 — Atravessar a mesa ao caminhar e ao sentar.**
A mesa ocupa x 1000–1470 (tampo y 752–768). O caminhar final e o sentar acontecem em x=1105, dentro desse volume; o tronco em pé (y 695–790) e sentado (y 750–845) cruza o tampo. Frames t=5,5 s (caminhando, mobília corta o peito), t=6,0–7,5 s (descida do corpo pela linha da mesa) confirmam. Em vista lateral o personagem é desenhado **na frente** da mesa, lendo-se como “atravessa a mesa”.

**P4 — O pé desliza ~52 px durante o sentar (sem foot-lock).**
FK do `_emit_action("sentar")`: o root apenas desce `y: 790→845` (sem translação x), enquanto `legR1` vai de ~+2° a −88°. O joelho viaja +55 px em x e o pé vai de x+3 (em pé) a x+55 (sentado) — os pés “andam” para a frente sozinhos enquanto o corpo desce reto. Não há plantio de pé; o movimento lê-se como deslize artificial (confirmado também pela ausência de qualquer tween de x do root em `sentar`/`levantar` no código, linhas 584–595).

**P5 — Pivô inicial da coxa deslocado 6 px do quadril.**
`.sm-rot { transform-origin: 50% 0% }` resolve no **bbox do grupo**. O bbox da coxa inclui o pé (`rect x=-4 w=22` → x −4..18; rect da coxa x −6..6) → bbox x[−6, 18] → 50% = **x=6**, não x=0 (junta do quadril). Canela: bbox x[−5, 18] → pivô em 6,5. Braços são simétricos (mão centrada) e ficam em 0 — por isso braços “funcionam” melhor que pernas. Todo giro de perna roda 6 px fora da junta (código: `_character_svg`, linhas 424–434, e CSS linha 719).

Confirmação de navegador: no HTML do render original, o Chrome/GSAP registrou `data-svg-origin="6 0"` em `#sm-legR-1` após inicialização. A leitura confirma o pivô fora do centro anatômico nessa etapa. A correção deve ancorar o pivô explicitamente e validar a cadeia quadril→joelho→tornozelo→pé no navegador; os testes FK existentes calculam juntas sem aplicar a matriz real do browser.

**P6 — Atuação e juntas parecem artificiais em ângulos extremos (comemoração).**
Os frames de t=14,5 / 15,5 / 17,3 s mostram a comemoração sentada como braços erguidos quase sem movimento corporal, com mãos circulares e juntas pouco legíveis; o pulinho está corretamente suprimido quando sentada. A inspeção visual confirma qualidade baixa, mas **não identifica sozinha** um descolamento sistemático do braço no ombro. No Chrome headless, o tween de rotação produz matrizes SVG e `data-svg-origin`; `getComputedStyle(...).transformOrigin` retorna `0px 0px` depois da inicialização GSAP. Isso não confirma a hipótese anterior de dupla compensação CSS×GSAP. A causa do aspecto estranho ainda exige validação de cada extremidade/junta; a recomendação é medir juntas em frames e simplificar o gesto antes de atribuir a falha a uma origem duplicada. O pulo em pé e o yoyo simultâneo independente dos dois antebraços continuam sendo escolhas mecânicas que merecem revisão artística.

**P7 — Os tweens se sobrepõem no fim do caminhar (risco demonstrado no JS; efeito visual ainda não medido).**
`_emit_walk` emite o tween restante em `[steps*step, duration]` e o settle em `[duration−0.28, duration]` **no mesmo intervalo** para os mesmos joints (linhas 513–521). É sobreposição de animações na mesma propriedade e pode mudar a pose final desse trecho; efeito de jitter/piscar não foi verificado. `correr` ainda emite um tween `_IDLE` extra em `[duration, duration+0.35]` que pode invadir o beat seguinte (linhas 579).

A sobreposição é verificável pelo timeline gerado; não foram analisados frames consecutivos nessa janela, portanto jitter/piscar é risco e hipótese, não defeito visual comprovado nesta auditoria.

### 3.2 Hipóteses e causas ainda não estabelecidas

**H1 — Dupla compensação CSS × GSAP: não confirmada; evidência atual a contradiz.**
O HTML declara origens CSS e o timeline também chama `gsap.set`. Contudo, a inspeção do workspace original no Chrome headless encontrou `data-svg-origin` e matrizes SVG GSAP, com `getComputedStyle(...).transformOrigin` em `0px 0px` depois da inicialização. Não há evidência para afirmar que o Chrome esteja aplicando duas origens na matriz final. A hipótese deve ser retirada como causa-raiz e qualquer mudança de origem deve depender de um teste focal de juntas, não de uma refatoração preventiva.

**H2 — Instabilidade de `getBBox` em `<g>` com elementos `fill="none"` no Chrome headless do HyperFrames (não confirmada).**
As âncoras invisíveis (`rect fill="none"` no head/upper) estabilizam o bbox do tronco superior e da cabeça. A hipótese de instabilidade do bbox ainda não foi demonstrada. A medição do Chrome abaixo confirma, porém, que o pivô inicial de uma perna já é deslocado pelo bbox calculado a partir das formas aninhadas.

**H3 — Jitter de seek causado por P7.**
Efeito visual não medido frame a frame; verificar extraindo 5 frames consecutivos na janela t≈5,7–6,0 s.

**H4 — Cabeça deslocando do pescoço nos yoyos de `repouso`/`digitar` (não estabelecido).**
O aspecto dos frames sugere movimento de cabeça a revisar, mas o efeito não foi quantificado contra o spec. A explicação anterior dependia de H1/H2 e não está demonstrada; medir o ponto da nuca e a orientação em frames intermediários antes de atribuir uma causa.

### 3.3 Por que os testes aprovados não pegaram isso

1. Os testes de FK (`test_studio_stickman.py`, Etapa 8.1) validam o rig **contra a mesma geometria de âncoras do motor** (chão 900, mesa 752–868, sit_y 845) — são autoconsistentes, não validam o personagem **contra o cenário desenhado** (assento/teclado/volume da mesa não entram nas contas).
2. Nenhum teste faz colisão personagem×cenário nem valida `walk_to_x`/`sit_y` contra as peças do SVG do cenário.
3. Nenhum teste renderiza no navegador e mede a posição real das juntas; a estrutura (ids, ordem de tweens, ausência de `Math.random`) é verificada, o pixel não.
4. O QA Stage 8 verificou o **contrato do MP4** (1080p30 silencioso) e uma checklist visual limitada (“pés no chão”, “coxas à frente”) que não cobriu interseções com mobília nem comemoração sentada.

### 3.4 Correções propostas (verificáveis, sem implementar nesta etapa)

| # | Correção | Critério de aceite |
|---|---|---|
| C1 | Reposicionar o personagem e redesenhar a relação entre cadeira, mesa e teclado; o centro do assento deve coincidir com o quadril sentado, com encosto, apoio e espaço de joelhos, mantendo a cabeça fora da faixa do teclado | frames em pé/sentado/ao teclado sem cruzamento da mesa ou cadeira com cabeça e tronco |
| C2 | Teste automático de colisão no `validate_spec`/`build_spec`: AABBs do personagem em pose sentada e em pé no destino vs peças do cenário (teclado, mesa, cadeira) | teste unitário novo falha com a geometria atual e passa com a corrigida |
| C3 | Foot-lock em `sentar`/`levantar`: plantar o pé (aninhar x do root na descida + ajuste de joelho), manter contato com o chão | série de frames intermediários com pé estacionário |
| C4 | Pivôs anatômicos explícitos e coesos com a hierarquia SVG, começando pelas pernas; evitar remover regras CSS/GSAP com base na hipótese de dupla compensação refutada | medir junta-pai e junta-filha no navegador e em poses extremas; erro ≤ 1 px |
| C5 | Âncoras `fill="none"` nas pernas (ou svgOrigin explícito) para neutralizar o deslocamento de 6 px do pé no bbox | pivô medido = junta anatômica |
| C6 | Eliminar sobreposições de tweens (settle após o fim do último passo; remover o `_IDLE` extra do `correr` invasivo) | busca por pares de tweens sobrepostos no JS gerado = vazia |
| C7 | QA visual automatizado: extrair frames em poses extremas (comemorar sentado, passagem pela mesa, meio do sentar) e comparar contra golden frames/rig conhecido | script QA novo no fluxo Stage 8 |
| C8 | Avaliar **reutilizar** o stack original (`SvgRigBuilder`/`CharacterRigRenderer` + skills `character-rigging`/`svg-character-animation`) em vez de evoluir o rig manual | decisão registrada em `decision_log` antes de investir mais no rig paralelo |

---

## 4. Integrações faltantes e duplicidades

### 4.1 Faltando conectar ao Studio

1. **Ponte `documentary-montage` → Studio** (pendência 3): converter `scene_plan`/`asset_manifest` em `scenes.json` com proveniência já preenchida — reutiliza os campos da Etapa 6.
2. **Legendas**: `subtitle_gen` / `remotion_caption_burn` fora da UI (pendência 4).
3. **Análise de bruto**: `source_media_review`, `transcriber`, `scene_detect`, `silence_cutter` não são invocados pelo modo “Editar vídeo bruto” (pendência 7).
4. **Narração PT**: só Kokoro EN no Studio; TTS cloud/local PT existentes no repositório (piper, azure, openai, elevenlabs…) não são expostos.
5. **Roteiro**: diretores `script-director`/`idea-director` do agente não geram insumo para o Studio.
6. **Registry HyperFrames**: cenas Stickman/HyperFrames usam apenas cartão de texto/rig próprio; blocos do registry ficaram para etapa futura (pendência 13).
7. **Corpus CLIP do documentário** (`corpus_builder`/`clip_search`) não alimenta a busca do Studio (que usa fan-out direto).

### 4.2 Duplicidades / paralelismos

| Capacidade | Implementação A (agente/pipeline) | Implementação B (Studio) | Risco |
|---|---|---|---|
| Personagem 2D articulado SVG+GSAP | pipeline `character-animation` + 6 tools (`SvgRigBuilder`, `PoseLibraryBuilder`, `ActionTimelineCompiler`, `CharacterRigRenderer`…) + skills `character-rigging`/`svg-character-animation`/`pose-library-design` | `lib/studio_stickman.py` (rig manual, presets fixos) | **alto** — dois rigs para manter; o Studio reinventou pivôs/poses sem as guardas do stack original (que inclusive tem reviewer de animação) |
| Montagem de documentário | `documentary-montage` (corpus CLIP, end-tag Remotion, LUT) | Studio timeline + export | médio — converte-los via ponte (item 1) em vez de duplicar lógica |
| Planejamento de cenas | `scene-director` + schema `scene_plan` | `studio_scene_generator` (parágrafo→cenas) | baixo — escalas diferentes; a ponte resolve |
| Runtimes de composição | pipeline documentário exige **Remotion** (end-tag) | Studio usa **HyperFrames** | médio — decidir política: manter Remotion só para end-tag/legendas ou trazer parity HyperFrames (já apontado no compose-director) |

---

## 5. Plano priorizado

### Frente A — Stickman (corrigir defeitos visuais) — prioridade máxima

1. **A1 (C1+C2):** redesenhar cadeira + tirar o sentar do volume da mesa + teste de colisão personagem×cenário no build/validate.
2. **A2 (C4+C5):** corrigir e medir as origens anatômicas; isso aborda o pivô da perna confirmado, sem assumir que resolverá os braços destacados.
3. **A3 (C3):** foot-lock em `sentar`/`levantar` (resolve P4).
4. **A4 (C6):** tweens sem sobreposição (resolve P7/H3).
5. **A5 (C7):** QA visual com frames extremos; re-executar Stage 8 e revisão humana do MP4 **antes** de qualquer nova funcionalidade.
6. **A6:** decidir (com o usuário, via `decision_log`) entre evoluir o rig do Studio ou migrar para o stack `character-animation` original (C8). Só depois: expressões, lip-sync, novos presets, compose multi-cena (pendências 14–15).

### Frente B — Documentários automáticos

1. **B1:** ponte `scene_plan`/`asset_manifest` → `scenes.json` (padrão `audio_mix_plan.py`; reutiliza proveniência da Etapa 6).
2. **B2:** busca stock em lote + filtro non-free do Wikimedia (próximo passo já aprovado no HANDOFF §5).
3. **B3:** legendas no Studio (SRT gerado + burn), reaproveitando `subtitle_gen`.
4. **B4:** narração PT — escolher provedor com o usuário (piper local grátis vs cloud pago) antes de integrar.
5. **B5 (opcional):** gerar o roteiro com os diretores do pipeline e importar como plano — sem reimplementar lógica no Studio.

### Frente C — Edição inteligente de vídeo bruto

1. **C-1:** no modo “Editar vídeo bruto”, rodar `source_media_review` (probe + transcrição + amostras) e mostrar o resumo na UI.
2. **C-2:** `scene_detect` + `silence_cutter` para propor marcadores de corte; o usuário confirma e os cortes entram na timeline existente (não destrutiva).
3. **C-3:** decidir arquitetura: automatizar dentro do Studio (local) vs usar os pipelines `clip-factory`/`hybrid` (agente) — registrar em `decision_log`.

Ordem sugerida geral: **A ( Stickman ) → B1/B2 (ponte + lote) → C-1** — A corrige um defeito já entregue ao usuário; B desbloqueia o fluxo documentário completo; C é funcionalidade nova.

---

## 6. Riscos, dependências e custos

| Risco/dependência | Impacto | Mitigação |
|---|---|---|
| Corrigir o rig quebra os 35 testes unitários atuais (eles codificam âncoras/pivôs errados) | médio | atualizar testes junto com C1–C5; o teste de colisão (C2) passa a ser a guarda |
| Causa do aspecto dos braços ainda indeterminada | médio | medir as juntas no navegador durante uma pose extrema antes de refatorar pivôs/origens |
| Renders de verificação Stickman/HyperFrames (~2–3 min cada, locais, sem custo API) | baixo | limitar a 2–3 renders por iteração; frames estáticos via captura de 1 s |
| Rig paralelo vs stack `character-animation` (duplicação) | alto (manutenção dupla) | decisão explícita do usuário antes de novas features Stickman |
| Remotion vs HyperFrames (documentário exige Remotion p/ end-tag; Studio é HyperFrames) | médio | manter os dois runtimes com papéis claros; nunca swap silencioso (regra do AGENT_GUIDE) |
| TTS PT: cloud = custo por caractere; local = qualidade variável | baixo/médio | amostrar antes de batch; registrar provider escolhido |
| Estado não commitado grande (12 modificados + ~30 não rastreados, incluindo todo o Studio 6–8.1) | **alto (perda de trabalho)** | após aprovação do usuário, commit de checkpoint sem mídias/WAVs/`.env` (regras do HANDOFF §6) — fora do escopo desta etapa |
| WAV aprovado e perfil de mix | crítico | manter guardas atuais; qualquer rota nova deve verificar sha256 antes/depois |
| Escala longa (40+ cenas): exportador 1 passe FFmpeg por corpo/transição | médio | otimizar passes quando a ponte documentário trouxer planos grandes |
| `documentary-montage` é beta; `cancel_event` não interrompe renders em andamento | baixo | já documentado nas limitações 6–8; tratar em etapa futura |

**Custos potenciais:** as três frentes do plano são majoritariamente locais (FFmpeg + HyperFrames/Node + Kokoro) — sem custo de API previsto, exceto TTS PT cloud (se escolhido) e eventuais buscas stock (gratuitas com rate limit). O custo real é de tokens/tempo de iteração: Stickman exigirá 2–4 ciclos render+frame-check; a ponte documentário é principalmente código de conversão.

---

## 7. Conclusão

- O **Studio** executa um fluxo local parcial de documentário (áudio → plano → stock manual por cena → montagem manual → export). Os 284 testes aprovados nesta retomada protegem contratos e regressões, mas não substituem inspeção visual.
- Os defeitos visuais do Stickman incluem alinhamento ruim com mesa/teclado, atuação artificial e um pivô inicial de coxa medido 6 px fora do quadril. A cadeira tem assento. A causa específica da aparência das juntas dos braços ainda não foi estabelecida; o conflito CSS×GSAP proposto pelo OpenCode não foi confirmado e a medição disponível o contradiz.
- As **maiores integrações faltantes** são a ponte `documentary-montage`→`scenes.json`, as legendas e a análise de vídeo bruto — todas reaproveitando ferramentas que já existem no repositório.
- A **duplicidade mais cara** é o rig Stickman do Studio versus o pipeline `character-animation` original; decidir isso antes de investir em expressões/lip-sync evita manter dois sistemas.

*Na auditoria, o código e o WAV aprovado não foram alterados; não houve staging ou commit. Este relatório foi finalizado com correções factuais e os resultados de confirmação abaixo.*

## 8. Confirmação final e correções ao relatório anterior

### Inventário conferido

Contagem direta de `skills/pipelines/`: **103 arquivos de diretor em 12 famílias**. O pipeline de teste `framework-smoke` não tem diretores nessa pasta. Os arquivos por família são:

| Família | Diretores presentes |
|---|---|
| `animated-explainer` → `explainer/` | asset, compose, edit, executive-producer, idea, proposal, publish, research, scene, script |
| `animation` | asset, compose, edit, executive-producer, idea, proposal, publish, research, scene, script |
| `avatar-spokesperson` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `character-animation` | asset, character-design, compose, executive-producer, idea, proposal, publish, research, rig-plan, scene, script |
| `cinematic` | asset, compose, edit, executive-producer, idea, proposal, publish, research, scene, script |
| `clip-factory` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `documentary-montage` | asset, compose, edit, executive-producer, idea, scene |
| `explainer/` (on-disk directory) | asset, compose, edit, executive-producer, idea, proposal, publish, research, scene, script |
| `hybrid` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `localization-dub` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `podcast-repurpose` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `screen-demo` | asset, compose, edit, executive-producer, idea, publish, scene, script |
| `talking-head` | asset, compose, edit, executive-producer, idea, publish, scene, script |

`animated-explainer.yaml` referencia os diretores no diretório `explainer/`; logo as duas linhas correspondentes acima são a mesma família lógica. Há 11 arquivos em `skills/meta/`, que fornecem governança e funções transversais, sem virar stages adicionais em cada pipeline. A lista das skills criativas e dos fornecedores descreve a arquitetura de conhecimento; não demonstra que todas estejam configuradas no ambiente ou integradas ao Studio.

### Pontos centrais verificados

- **Inventário documental:** o manifesto `pipeline_defs/documentary-montage.yaml` define cinco stages próprios: `idea`, `scene_plan`, `assets`, `edit`, `compose`. O campo `required_skills` também declara os diretores executive-producer, idea, scene, asset, edit, compose e as duas meta skills reviewer/checkpoint. Não declara stages research, script, proposal ou publish. O pipeline exige o tool `video_compose`; seus diretores impõem Remotion para o end-tag. O Studio é um fluxo separado e não consome artifacts do Backlot.
- **Estado visual real:** `source.json` associa os frames ao MP4 Etapa 8.1 de SHA-256 `02afcbb7…`; seu HTML e o HTML da demonstração mais recente em `projects/openmontage-studio/renders/stickman-workspaces/cena-stickman-20261014-041725-985392/` são iguais ao HTML produzido pelo motor atual para o respectivo `spec.json`. Isso confirma que os frames auditados representam o motor em uso, não apenas um arquivo antigo.
- **Pivôs:** no HTML original carregado em Chrome headless com GSAP, o pivô inicial `data-svg-origin` de `#sm-legR-1` foi `6 0`; os membros são construídos dentro de grupos cuja caixa inclui o pé. É evidência direta de um pivô de quadril deslocado. A lista de testes FK em `tests/unit/test_studio_stickman.py` não executa a cadeia de transformações SVG usada pelo browser.
- **Hipótese CSS×GSAP:** a origem dupla não pode ser relatada como causa. O navegador mostra a origem final GSAP em matriz SVG, CSS transform origin computado como `0px 0px`, e não foi demonstrada uma segunda aplicação. A causa concreta dos gaps dos braços continua em aberto.
- **Mobiliário:** o SVG contém assento, mas não encosto; a coluna e a linha do tronco coincidem em parte. O teclado ocupa `x=1062..1212`, `y=738..752`, e a cabeça sentada ocupa `x=1077..1133`, `y=692..748`; há sobreposição vertical de 10 px na borda inferior da cabeça. A mesa começa em `y=752` e a pose sentada começa na mesma altura, enquanto o personagem é declarado depois do mobiliário e, portanto, é desenhado à frente dele. Esses dados explicam o aspecto de interseção sem atribuí-lo à falta de assento.
- **Transições:** o cálculo FK da Etapa 8.1 indica que a perna muda de ângulo enquanto o root não se desloca lateralmente; o pé avança cerca de 55 px durante o movimento sentado. O timeline JS também cria tweens de settle que ocupam parte do trecho final dos tweens de marcha, mas a consequência em pixels ainda não foi medida.
- **Vídeo bruto:** `openmontage_studio.py` declara o arquivo selecionado em modo somente leitura, sem análise ou edição automática. A timeline existente monta arquivos completos de imagem/vídeo e sincroniza todos os visuais ao WAV selecionado; o exporter elimina áudio dos itens (`-an`) e remuxa esse WAV ao final. Portanto, há montagem manual de brutos com áudio original substituído pelo WAV, mas não há decupagem inteligente, preservação de áudio fonte ou conformação multiclip com som original no Studio.
- **Fontes stock:** `lib/studio_stock_search.available_stock_source_names()` retornou `pixabay_video` e `wikimedia` no ambiente auditado. O helper lista ainda Pexels como opção suportada, mas indisponível nesta execução. Não declarar as três como configuradas.
- **HyperFrames:** a validação Stage 8 anterior registrou execução real via HyperFrames 0.8.156/Node 24. Nesta consulta ao registro, `hyperframes_compose` foi classificado indisponível por timeout de 5 segundos ao resolver o pacote npm. É um sinal de disponibilidade inconsistente/offline, não evidência de que os renders registrados foram fictícios ou de que o runtime esteja sempre disponível.
- **Testes e proteção:** comando da suíte descrita no `HANDOFF.md`, ampliado com os testes de adapters stock e governança, terminou com **284 passed, 3 xfailed** em 99,12 s. Os `xfail` são a expectativa da suíte, não falhas novas. O SHA-256 lido do WAV protegido `D:\YouTube-Automacao\Audios\audio_final_documentario.wav` continuou `82808d024b02236e0eff891ff74d6d05879715e3e1bc13c2f667869dbe80692c` na leitura final. Nenhum render novo foi produzido nesta retomada.

### Inventário consolidado de capacidades relevantes

| Capacidade original | Estado fora do Studio | Estado no Studio |
|---|---|---|
| Pesquisa factual e verificação web | diretores `explainer/research-director` e `animation/research-director`; artifacts e registry do agente | ausente; o Studio não gera roteiro nem research brief |
| Story/roteiro | stage director de `explainer`, `animation`, `cinematic`, `hybrid`, etc. | ausente; caixa de texto aceita narração já pronta |
| Documentário por imagens de arquivo/stock | `documentary-montage` com busca direta ou corpus/CLIP e pipeline agent-first; estabilidade beta | fluxo local parcial: plano, busca individual, edição manual e render; sem import da sequência documental e sem corpus CLIP integrado |
| Narração e música | múltiplos provedores pelo registry, sujeita a disponibilidade/configuração | Kokoro local em inglês, três vozes usadas no Studio, catálogo/mixagem; outros idiomas são apenas preparatórios na UI |
| Legendas | gerador SRT/VTT e queima Remotion estão no repositório | ausente na UI local |
| Análise de bruto | `source_media_review`, análise/frame sampling, transcription e scene detect existem; clip-factory/talking-head/hybrid definem fluxos do agente | ausente na edição bruta do Studio; entrada somente leitura e adição manual à timeline |
| Corte e exportação | FFmpeg trimming/stitching, silence cutter e ferramentas de pipeline | corte de cena via duração/trim da timeline; transições simples; export H.264/AAC. Sem sugestão automática de cortes ou preservação de áudio dos takes |
| Personagem 2D | pipeline `character-animation` e tools de spec, rig SVG, pose, action timeline, renderer e reviewer; Ink Theater/Ink Puppet como stack separado | rig independente de dois personagens e presets rígidos; renderiza, mas a qualidade visual não passa na revisão humana atual |

### Ajustes de prioridade para eventual implementação

1. Corrigir as colisões/oclusão e o pivô de perna confirmado; estabelecer uma verificação de juntas no browser e pedir avaliação humana do MP4. Medir separadamente gaps de braços antes de mexer nos pivôs deles.
2. Auditar se a interface deve reutilizar o sistema `character-animation` existente ou manter o rig de preset do Studio. A auditoria confirma duplicidade arquitetural, mas não recomenda migração sem comparar a qualidade e o custo de integração.
3. Para documentários, priorizar a ponte dos artifacts `documentary-montage` para `scenes.json`, preservando proveniência e gates de revisão; depois avaliar lote/filtros de licença, legendas e fluxo de áudio conforme os requisitos.
4. Para brutos, começar com uma proposta de cortes após `source_media_review`/transcrição/scene detect e enviar os segmentos aprovados à timeline existente. Definir explicitamente política de áudio original versus WAV antes de exportar uma versão editada.

Este é um relatório de auditoria, não uma aprovação para executar essas quatro frentes. `git status` tinha alterações existentes das Etapas 6–8.1 antes desta confirmação; elas foram preservadas. Não foram alterados arquivos de código nem feitos staging/commits nesta auditoria.
