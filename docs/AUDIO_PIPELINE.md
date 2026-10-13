# Mixagem documental local

A integração usa `audio_mixer` (FFmpeg) e a entrada `audio_path` já existente
em `video_compose`. Não chama serviços pagos e não publica conteúdo.

## Perfil aprovado: informação pendente

O arquivo `instrucoes_codex.txt` confirma `duck_level: -35` e ganho final
`master_gain_db: 3`, mas não informa o ganho numérico da narração. Esse valor
precisa ser confirmado antes de ativar o perfil. O adaptador recusa ganho
ausente ou `null`; não adota silenciosamente zero. Áudio previamente
amplificado não deve receber o mesmo ganho novamente.

No estágio de edição, gravar em `edit_decisions.metadata.audio_mix`:

- `narration_gain_db`: ganho confirmado para o arquivo de voz utilizado;
- `duck_level`: `-35`;
- `master_gain_db`: `3`;
- `normalize`: `false`, para preservar o equilíbrio manual.

Manter os assets em `asset_manifest.assets`; a narração em
`audio.narration.segments` com `asset_id`, `start_seconds` e, opcionalmente,
`end_seconds`; música em `audio.music`; efeitos em `audio.sfx`. Gravar
`total_duration_seconds` e usar `audio.music.ducking: true`.

`duck_level` converte dB para o nível linear usado pelo compressor existente.
Não é uma promessa de atenuação medida constante. A compensação de volume,
a normalização da soma final e os tempos históricos do compressor foram
preservados para não mudar o som de chamadas anteriores. O adaptador ativa
`preserve_speech_volume` para não dividir a narração pelo número de segmentos.
Trechos de voz sobrepostos são somados; conferir
os horários da edição. A correção da unidade
dos tempos do compressor deve ser tratada como uma mudança de som separada.

## Execução no estágio compose

Depois de resolver as aprovações e ler as skills do estágio/ferramentas:

```python
from lib.audio_mix_plan import documentary_mix_inputs
from tools.tool_registry import registry

registry.discover()
mix_inputs = documentary_mix_inputs(edit_decisions, asset_manifest, project_dir)
mixed = registry.get("audio_mixer").execute(mix_inputs)
if not mixed.success:
    raise RuntimeError(mixed.error)

rendered = registry.get("video_compose").execute({
    "operation": "render",
    "edit_decisions": edit_decisions,
    "asset_manifest": asset_manifest,
    "proposal_packet": proposal_packet,
    "audio_path": mixed.data["output"],
    "output_path": str(project_dir / "renders" / "final.mp4"),
})
if not rendered.success:
    raise RuntimeError(rendered.error)
```

O adaptador apenas traduz parâmetros e resolve caminhos; a decisão de executar
etapas continua com o agente. Ele não gera narração nem escolhe música. Os
caminhos de assets podem ser absolutos, relativos ao projeto ou relativos ao
repositório começando por `projects/`.

A faixa é salva em `projects/<projeto>/assets/audio/mixed_audio.wav`. Conferir
picos, duração e clareza da voz antes de usar o arquivo final. O adaptador
documental aplica limitador de pico de amostra em -1 dBFS depois dos ganhos
aprovados, preservando o ganho nominal e atenuando somente picos acima do teto.
Configure `metadata.audio_mix.peak_limit_db` para outro teto. Chamadas diretas
ao `audio_mixer` continuam sem limitador se o campo for omitido.
`normalize=true`, se explicitamente escolhido, normaliza primeiro e aplica os
ganhos finais e o teto de pico depois.

Para documentários longos, preparar uma trilha que cubra a duração aprovada.
`target_duration` corta ou completa com silêncio; não repete música curta.
Janelas de silêncio precisam estar aplicadas à trilha antes desta chamada.
Registrar a licença e a origem de cada música antes de produção monetizada;
o catálogo local atual não contém essa comprovação.
