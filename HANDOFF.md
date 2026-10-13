# HANDOFF — OpenMontage Studio (Etapa 4)

Documento de transferência do estado atual do **OpenMontage Studio**, o fluxo local do OpenMontage para automatizar documentários de 8–20 minutos para o YouTube, com narração/mixagem aprovadas e montagem não destrutiva.

---

## 1. Contexto

O Studio é uma aplicação Tkinter isolada do pipeline orquestrado (`pipeline_defs/`):

- **Áudio local:** narração Kokoro (inglês) + seleção de música por catálogo local + mixagem com perfil aprovado fixo.
- **Montagem local:** timeline por quadros (30 fps, 1080p), transições cut/crossfade/fade, encaixe exato no WAV via `Ajustar ao WAV`, exportação MP4 H.264/AAC com verificação.
- **WAV aprovado (somente leitura):** `D:\Youtube-Automacao\Audios\audio_final_documentario.wav`
  - sha256 `82808d024b02236e0eff891ff74d6d05879715e3e1bc13c2f667869dbe80692c`
  - 181 278 bytes
  - Este arquivo e o perfil de mixagem aprovado **não podem ser alterados** pelo Studio.

Arquitetura de referência: `AGENT_GUIDE.md`, `PROJECT_CONTEXT.md`.

---

## 2. Funcionalidades concluídas

### Etapa 3 (já em checkpoint `ff9dbd2`)

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

### Etapa 4 (este commit)

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

### Garantias verificadas (QA Stage 4)

- Importação é **atômica**: plano com mídia ausente é rejeitado por inteiro e a timeline atual não muda.
- WAV do plano ≠ WAV ativo → diálogo obrigatório; recusa mantém o WAV aprovado.
- Exportação de MP4 a partir do plano importado: 1920×1080, 30 fps, H.264, AAC, nº de quadros = quadros do WAV.
- Áudio exportado **bit a bit igual** à conversão AAC direta do WAV aprovado (nenhum ganho/efeito novo).
- Round-trip: timeline → `scenes.json` → recarrega idêntico.
- Fingerprints (sha256/size/mtime) do WAV aprovado e das mídias de teste inalterados antes/depois.

---

## 3. Testes

Executar na raiz do repositório:

```bash
# Unitários + UI + exportação do Studio
.venv/Scripts/python.exe -m pytest tests/unit/test_studio_scenes.py tests/test_studio_timeline_ui.py tests/test_studio_timeline.py tests/test_openmontage_studio.py tests/tools/test_studio_export.py tests/tools/test_studio_export_availability.py -q

# QA local Stage 3 (regressão do fluxo manual + WAV aprovado)
.venv/Scripts/python.exe scripts/validate_studio_stage3.py

# QA local Stage 4 (scenes.json + exportação + integridade do WAV)
.venv/Scripts/python.exe scripts/validate_studio_stage4_scenes_import.py
```

Resultado da última execução (2026-10-13):

- pytest Studio: **97 passed**
- QA Stage 3: **passed** (MP4 verificado, áudio = AAC direto, fontes inalteradas)
- QA Stage 4: **passed** (import 4 cenas, auto-fit, export verificado, round-trip, import atômico bloqueado, recusa de troca de WAV, WAV aprovado inalterado)

Os scripts QA criam diretórios únicos em `projects/openmontage-studio/` (gitignored) e não usam APIs pagas.

---

## 4. Pendências (fora do escopo da Etapa 4)

1. **Gerador local de `scenes.json` a partir do texto da narração** — segmentação por parágrafos, duração proporcional às palavras; 100% local, sem API.
2. **Resolução de mídia por palavras-chave** em pastas locais a partir das `note`s/ids do plano.
3. **Ponte com o pipeline `documentary-montage`** — converter `scene_plan`/`asset_manifest` do agente em `scenes.json` para revisão/export no Studio.
4. **Legendas** (SRT / queimadas) — UI ainda marca como “não integrado”.
5. **Narração em português** — Kokoro desta instalação gera só inglês; PT/DE/ES são preferências preparatórias.
6. **Alvo rígido de duração** — hoje a duração final sempre segue o WAV de narração.
7. **Edição automática de vídeo bruto** — modo “Editar vídeo” só registra o arquivo; não analisa nem corta.
8. **Roteiro automático e pesquisa/geração de mídia** — ainda manuais.
9. **Escala longa (40+ cenas)** — o exportador faz 1 passe FFmpeg por corpo + 1 por transição; aceitável hoje, otimização de passes é futura.

---

## 5. Próximo passo recomendado

Implementar o **gerador local de `scenes.json`** a partir do texto já colado no campo de narração (fase B do plano Etapa 4/5):

- Entrada: parágrafos do texto + duração total do WAV (ou duração planejada).
- Saída: arquivo `scenes.json` no formato `version: "1.0"` com `duration_seconds` proporcional e `transition` padrão `cut`/`crossfade` alternado.
- Integração: botão “Gerar plano do texto…” no editor de timeline ou no painel Áudio; em seguida o usuário preenche `media` e usa o fluxo de import já validado.
- Critério de aceite: gerar → preencher mídias → importar → exportar, tudo local, sem tocar no WAV aprovado.

---

## 6. Regras permanentes (não negociáveis)

- **Não alterar** `D:\Youtube-Automacao\Audios\audio_final_documentario.wav` nem o perfil de mix aprovado.
- Exportação nunca sobrescreve mídia original, WAV existente nem MP4 existente.
- Importação de plano nunca troca o WAV ativo sem confirmação explícita.
- Preferências de idioma/legenda/estilo permanecem preparatórias até integração real.
- Nenhum commit deve incluir mídias, WAVs de teste, `.env`, chaves, `backups/`, `projects/`, `__pycache__` ou históricos de ferramentas (`.aider*`).

---

## 7. Mapa de arquivos (Etapa 4)

```
lib/studio_scenes.py                          # contrato scenes.json (load/save/convert)
schemas/studio/scenes.schema.json             # schema JSON do plano
lib/studio_timeline_ui.py                     # UI: import/export + confirmações
openmontage_studio.py                         # textos de ajuda dos modos
tests/unit/test_studio_scenes.py              # 34 unitários do formato
tests/test_studio_timeline_ui.py              # +6 testes de UI (import/export/WAV)
scripts/validate_studio_stage4_scenes_import.py  # QA ponta a ponta
scripts/validate_studio_stage3.py             # QA de regressão (inalterado, ainda verde)
```

Relatórios de QA (não versionados): `projects/openmontage-studio/qa-stage3-*/validation.json`, `qa-stage4-*/validation.json`.
