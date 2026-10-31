# SecurityWebCam

Aplicação pessoal em Python para gravação de câmera e microfone no Windows, com segmentação de arquivos MP4 e painel local de controle.

## Recursos

- Seleção explícita dos dispositivos de captura.
- Controle da gravação pelo painel local.
- Organização das gravações em segmentos.
- Configuração de destino e opções de retenção.

## Requisitos gerais

Python, FFmpeg/FFprobe e dispositivos de captura compatíveis. Consulte os arquivos de configuração de exemplo e as dependências versionadas antes da instalação.

## Estrutura

| Pasta ou arquivo | Conteúdo |
| --- | --- |
| `securitywebcam/` | Implementação da aplicação. |
| `scripts/` | Scripts de instalação e manutenção. |
| `tests/` | Testes automatizados. |
| `config.example.json` | Exemplo de configuração. |
| `requirements.lock` | Dependências fixadas. |

## Uso e desenvolvimento

Configure seu próprio ambiente e destino de gravação. Não versione vídeos, credenciais ou configurações pessoais. Recursos de câmera, áudio e acesso remoto dependem de validação no dispositivo onde a aplicação será usada.

Este README apresenta as capacidades do projeto; não afirma que todos os cenários de hardware, acesso remoto ou armazenamento foram validados.

## Licença

Consulte [LICENSE](LICENSE).
