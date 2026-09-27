# SecurityWebCam

Gravador pessoal para Windows, com câmera e microfone selecionados explicitamente, segmentos MP4 e painel privado em português brasileiro.

**Estado da entrega:** captura local nos três modos e recuperação de falhas verificadas neste computador. Acesso externo por Tailscale, novo login do Windows, desconexão física de dispositivos e reprodução no celular ainda exigem validação pelo proprietário. A integração OneDrive verifica a cópia local; **não confirma upload ou disponibilidade na nuvem**. Consulte [as evidências e pendências](docs/TESTES.md).

## Instalação e primeira execução

Requisitos testados: Windows 11 Home build 26200, Python 3.14 x64, FFmpeg/FFprobe 8.0.1. Uso diário sem administrador. O driver/serviço do Tailscale pode exigir elevação na instalação.

1. Instale [Python 3.14 para Windows](https://www.python.org/downloads/windows/) para o usuário atual, incluindo o launcher `py`.
2. Instale FFmpeg 8.0.1, com `ffmpeg.exe` e `ffprobe.exe` no PATH. Há builds Windows indicados na [página oficial do FFmpeg](https://ffmpeg.org/download.html#build-windows), incluindo Gyan. A instalação usada nos testes já existia via Chocolatey. Não substitua drivers ou permissões de privacidade.
3. Clone e execute no PowerShell:

```powershell
git clone https://github.com/GuiPaicheco/SecurityWebCam.git
cd SecurityWebCam
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1
```

O instalador cria `.venv`, instala versões fixadas em `requirements.lock` e adiciona dois atalhos no menu Iniciar: **SecurityWebCam** e **Encerrar SecurityWebCam**. `-NoLaunch` instala sem abrir. Não mova a pasta do projeto sem executar novamente o instalador; se autoinicialização estiver ativa, desative e reative pela interface após a mudança.

Na primeira abertura, defina e confirme uma senha de pelo menos 12 caracteres. Essa janela aparece somente no cadastro inicial. O painel abre em [http://127.0.0.1:8765](http://127.0.0.1:8765). Entre, abra **Configuração**, selecione câmera/microfone, escolha uma pasta existente e salve. Clique **Iniciar**. Por padrão: áudio + vídeo, 640×480, 30 fps, qualidade equilibrada, segmentos de 600 segundos, mínimo livre de 2 GiB. Consulte os formatos do dispositivo antes de alterar resolução/fps; combinações não suportadas geram erro no painel e nova tentativa, sem substituir silenciosamente a seleção.

**Pausar** finaliza o segmento atual; **Retomar** abre nova sessão. **Parar** finaliza a captura. Fechar a aba não encerra o aplicativo. Use o atalho **Encerrar SecurityWebCam** para finalizar também o servidor. A gravação não é retomada numa abertura manual sem clicar Iniciar; o início automático só acontece quando a opção correspondente estiver habilitada.

Execução técnica equivalente:

```powershell
.\.venv\Scripts\pythonw.exe launcher.pyw --open
.\.venv\Scripts\python.exe -m securitywebcam --shutdown
```

## Inicialização automática

Desativada por padrão. Com a captura parada, marque **Iniciar aplicativo e captura após meu login no Windows**, salve e confirme o estado da opção. Desmarcar e salvar remove o registro. Utiliza somente `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valor `SecurityWebCam`, apontando para `pythonw.exe launcher.pyw --autostart`. Não cria serviço, tarefa escondida nem entrada em HKLM. O aplicativo continua identificável no painel, nos atalhos e no Gerenciador de Tarefas (`pythonw.exe` e FFmpeg).

O lançamento pós-login está implementado, mas **não foi testado em um novo login real** nesta sessão. Procedimento de aceitação: habilitar pela interface, salvar o trabalho aberto, sair do Windows, entrar novamente, abrir o painel, verificar estado Gravando e reproduzir o primeiro segmento. Depois desabilitar, repetir o login e verificar que não inicia.

**Antes do login: não suportado nesta versão e não comprovado neste hardware.** A arquitetura usa a sessão do usuário. A documentação Microsoft informa que serviços ficam isolados na sessão 0; isso não garante acesso aos dispositivos DirectShow nem substitui teste real. Não instalamos serviço privilegiado para prometer uma capacidade não demonstrada. Referências: [Run/RunOnce](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys) e [serviços interativos](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services).

## Gravação, falhas e arquivos

- FFmpeg lê DirectShow e codifica H.264/AAC em fluxo. O muxer de segmentos gira os arquivos sem reiniciar a câmera a cada segmento; memória limitada a buffers, sem carregar um segmento inteiro.
- Nomes: `AAAAMMDDTHHMMSS-0300_av_UUID_000001.mp4`. O offset representa o fuso vigente no momento da captura; modos `audio`, `video`, `av`. O índice complementa o identificador da sessão.
- Durante a captura, extensão `.mp4.partial`. O CSV do FFmpeg informa os segmentos encerrados. Só após FFprobe, remontagem em MP4 convencional com índice no início, decodificação integral, SHA-256 e publicação no catálogo um arquivo fica disponível no painel e na fila OneDrive.
- MP4 fragmentado reduz a perda em interrupções. Arquivos concluídos ficam independentes. No reinício, arquivos não catalogados são validados; fragmentos inválidos permanecem no destino para diagnóstico e **não são publicados**. O último trecho em gravação pode ser perdido. Não há promessa de recuperação de todo arquivo interrompido.
- Windows Job Object encerra descendentes do FFmpeg se o aplicativo morrer. Um bloqueio por instalação impede duas instâncias sobre o mesmo catálogo. Falha do encoder ou ausência de progresso por 30 segundos provoca recuperação com espera progressiva até 60 segundos.
- Modo combinado: escolha aguardar ambos ou continuar com o disponível. A segunda opção tenta áudio/vídeo separado quando necessário e tenta voltar a ambos a cada 60 segundos. O painel mostra o modo realmente usado. Uma falha pode gerar uma lacuna entre segmentos; não há troca de hardware sem interrupção.
- A pausa, a troca de modo/dispositivo e a troca do destino exigem reabertura da captura. Relógio, latência dos drivers e buffers influenciam a sincronização. Timestamps dos segmentos completos foram medidos; sincronização perceptiva prolongada exige o teste descrito em `docs/TESTES.md`.

## Destino, contingência e retenção

Selecione uma pasta local ou em mídia externa. O aplicativo cria nela uma subpasta exclusiva `SecurityWebCam-<identificador da instalação>` com marcador de propriedade. Arquivos de outras pastas e arquivos não catalogados nunca entram na exclusão automática.

O destino selecionado é associado ao **GUID do volume Windows e caminho relativo**. Isso permite reencontrar a mídia após mudança de letra. Ao formatar/trocar o disco, selecione-o novamente. Compartilhamentos UNC não fazem parte da garantia desta versão: a identificação estável exige volume local Windows.

Na ausência do destino, escolha **Aguardar** ou **Contingência**. A pasta de contingência deve existir em um disco local. Quando o destino volta, segmentos concluídos migram por cópia, comparação de tamanho/SHA-256, atualização do catálogo e só então remoção da origem. Conflitos de mesmo nome/conteúdo diferente são preservados e registrados, sem sobrescrita. Segmentos ativos não migram.

Políticas locais independentes:

| Opção | Comportamento |
|---|---|
| Retenção em dias = 0 | Desativada |
| Limite de armazenamento = 0 | Sem limite de tamanho |
| Dias/tamanho configurados | Exclui os mais antigos elegíveis dentro das pastas administradas |
| Preservado ou cópia pendente | Não exclui automaticamente |
| Espaço mínimo livre | Para/aguarda quando insuficiente; não autoriza exclusões adicionais por si só |

Antes de iniciar, há reserva estimada para dois segmentos (captura e finalização) e 32 MiB, além do mínimo livre. Quando um limite de tamanho estiver ativo, a retenção pode liberar espaço para essa reserva antes de iniciar. Durante a gravação há verificação periódica. A estimativa não garante proteção contra outro programa consumindo o disco entre verificações. Se todos os arquivos estiverem preservados/pendentes, o sistema aguarda em vez de descartá-los. Fragmentos inválidos não são apagados automaticamente e podem precisar de inspeção manual.

## Celular com o computador ligado: Tailscale Serve

1. Instale o [Tailscale oficial no Windows](https://tailscale.com/download/windows) e no celular. O script `scripts/install-tailscale.ps1` baixa o instalador oficial, verifica sua assinatura Authenticode e inicia a instalação. Aprove o UAC somente para instalar o driver/serviço. Entre com sua conta nos dois dispositivos.
2. No painel administrativo do Tailscale, habilite aprovação de dispositivos e restrinja as regras de acesso aos seus dispositivos/usuário. Revise regras preexistentes que autorizem outros integrantes da tailnet. Não compartilhe este computador com terceiros.
3. Obtenha o nome DNS exato do computador com `tailscale status --json` ou pelo painel administrativo, por exemplo `computador.tail123.ts.net`.
4. Com a captura parada, informe esse nome em **Configuração → Acesso privado pelo celular**, marque a opção e salve. Clique **Configurar Tailscale Serve** no painel local. Alternativa no PowerShell:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg http://127.0.0.1:8765
& 'C:\Program Files\Tailscale\tailscale.exe' serve status
```

Se o Tailscale solicitar habilitar HTTPS na tailnet, conclua essa etapa na sua conta. Não use `funnel`, não encaminhe portas no roteador, não abra a porta 8765 no firewall e não altere o bind do aplicativo para `0.0.0.0`.

5. No celular, conecte o Tailscale, abra `https://<nome exato do computador>` e entre com a senha do SecurityWebCam. Filtre por data/horário/modo, reproduza ou baixe. Há paginação de 100 itens e suporte a HTTP Range para vídeo.

Serve fornece HTTPS privado dentro da tailnet; o aplicativo acrescenta senha, sessão HttpOnly/SameSite, cookie Secure no endereço remoto, expiração de 12 horas e proteção CSRF. O servidor aceita somente os hosts locais fixos e o nome remoto explicitamente configurado. Downloads usam IDs do catálogo, nunca caminhos fornecidos pelo navegador. [Documentação oficial do Serve](https://tailscale.com/docs/features/tailscale-serve).

**Revogação:** se perder o celular, remova/revogue o dispositivo no painel Tailscale. Em SecurityWebCam, altere a senha para invalidar todas as sessões. Desativar a opção remota e salvar bloqueia o host remoto no aplicativo. Para remover a publicação deste aplicativo, use `tailscale serve --https=443 off` **somente se esse listener for exclusivo do SecurityWebCam**; confira `serve status` e preserve outras configurações. Reiniciar o aplicativo também invalida sessões existentes.

Esta etapa depende de instalação/login do Tailscale e de teste real na rede móvel. Não foi declarada validada remotamente no ambiente de entrega.

## Celular com o computador desligado: OneDrive

Funcionalidade independente e desativada por padrão. Use o cliente oficial do **OneDrive pessoal já autenticado**. Escolha uma pasta sincronizada dedicada, separada do destino e da contingência; marque a opção e salve. O aplicativo cria sua subpasta exclusiva, organizada por `ano/mês/dia`. Não solicita nem armazena senha/token Microsoft. Ative a [verificação em duas etapas da conta Microsoft](https://support.microsoft.com/account-billing/how-to-use-two-step-verification-with-your-microsoft-account-c7910146-672f-01e9-50a0-93b4585e7eb4).

Estados distintos no painel:

| Estado | Significado |
|---|---|
| Gravado localmente | Segmento finalizado, decodificado e catalogado |
| Cópia pendente | Fila persistente no SQLite; nova tentativa após erro ou reinício |
| Copiado para a pasta do OneDrive | Tamanho e SHA-256 conferem na cópia local sincronizável |
| Sincronizado na nuvem | **Não utilizado:** não há confirmação confiável de upload nesta integração |

O cliente oficial, não este aplicativo, retoma uploads após quedas da internet. A fila do aplicativo trata indisponibilidade da pasta, erro de cópia e falta de espaço local, com tentativas progressivas. Copiar para uma pasta chamada OneDrive, por si só, não prova que ela esteja autenticada/sincronizada. Confira a conta e o caminho no cliente.

Filtros: todos os modos ou modos escolhidos; horas locais inteiras, por exemplo `8,9,10`; somente preservados. Os critérios são combinados. Filtros de horário/mode se aplicam ao início do segmento; horário de verão segue o Windows. Novas configurações valem para novos segmentos e novas marcações; a fila existente continua persistida. Desativar cópias suspende o processamento sem perder a fila. Se mudar a pasta, itens que já tiveram destino persistido continuam naquela pasta para impedir duplicação ambígua.

**Retenção OneDrive separada**, 0 por padrão. Só remove cópias catalogadas pelo aplicativo, quando habilitada, respeitando preservados. Essa exclusão propaga para a nuvem pelo cliente. A retenção local nunca exclui a cópia OneDrive. Arquivos locais pendentes não são removidos pela retenção.

O painel mostra o total pendente e o espaço do disco da pasta OneDrive. **A cota da conta é desconhecida**: consulte o aplicativo OneDrive; falta de cota pode impedir o upload mesmo com espaço no disco. O armazenamento sincronizado pode ocupar espaço tanto no destino como na pasta OneDrive.

Para validar acesso com o PC desligado: grave um segmento curto, pare a captura, aguarde “Copiado para a pasta do OneDrive”, confira o upload concluído no cliente/web do OneDrive, abra o arquivo no aplicativo do celular, encerre SecurityWebCam/desligue o PC e abra novamente o arquivo pela nuvem no celular. Registre essa validação como pendente até completá-la. Arquivos ainda em gravação, pendentes ou apenas copiados sem upload não ficam garantidamente acessíveis depois de desligar. [Significado dos ícones oficiais](https://support.microsoft.com/pt-br/onedrive/what-do-the-onedrive-icons-mean).

Alternativa testável quando a conta não está configurada: habilite a cópia para uma pasta local de teste, gere um segmento e compare seu SHA-256 com a cópia. Isso valida fila/cópia, não armazenamento em nuvem. Há teste real de cópia com mídia sintética na pasta indicada pelo ambiente OneDrive, sem confirmação de upload.

## Arquitetura e segurança

- **Python + Flask/Waitress:** stack pequena para Windows, sem servidor de desenvolvimento na execução diária. Interface web responsiva evita duas implementações de desktop/celular. Arquivos estáticos locais, sem CDN ou telemetria.
- **FFmpeg DirectShow:** seleção dos dispositivos reais, formatos oferecidos pelo driver, codecs amplamente reproduzíveis. O processo é criado sem janela de console. [Referência DirectShow](https://ffmpeg.org/ffmpeg-devices.html#dshow).
- **SQLite WAL + synchronous FULL:** catálogo, fila e eventos com transações. JSON salvo por escrita temporária, fsync e substituição atômica. Log circular de até 2.001 eventos.
- **Senha:** PBKDF2-HMAC-SHA256, 600 mil iterações e salt aleatório. Só hash/salt no disco, em `%LOCALAPPDATA%\SecurityWebCam`, com ACL restrita ao proprietário e SYSTEM. Sessões aleatórias em memória, invalidadas em reinício/troca de senha; limite de tentativas de login. Não há credenciais Microsoft/Tailscale no aplicativo.
- Configuração exportada é uma lista explícita de campos não secretos. Não inclui hash, salt, sessões, GUID de volume ou tokens. Caminhos de pastas podem revelar nomes locais: revise antes de compartilhar o arquivo exportado.
- Sem shell remoto, desktop remoto, execução de comandos fornecidos pela API ou acesso arbitrário a arquivos. A ação Serve executa um comando fixo local, autenticado; não aceita argumentos do cliente.
- Gravações **não são criptografadas pelo aplicativo**. Permissões do destino são as do Windows; para confidencialidade em disco, escolha uma pasta privada e proteção de dispositivo/volume disponível no seu Windows. Administradores e processos executados como seu usuário não fazem parte da fronteira de isolamento deste aplicativo.

## Consumo e custos

Estimativas de 24 h contínuas, antes da pequena sobrecarga do contêiner:

| Qualidade (áudio + vídeo) | Taxa aproximada | GiB/dia | GiB/30 dias |
|---|---:|---:|---:|
| Econômica | 0,8 Mb/s + 128 kb/s | 9,33 | 280,02 |
| Equilibrada | 2 Mb/s + 128 kb/s | 21,40 | 642,12 |
| Alta | 5 Mb/s + 128 kb/s | 51,58 | 1547,40 |
| Somente áudio | 128 kb/s | 1,29 | 38,62 |

São estimativas baseadas na taxa alvo, não medições garantidas. Qualidade, cena, dispositivo e carga de CPU alteram o resultado. Cópias OneDrive consomem cota e banda de upload; um plano de armazenamento pode ser necessário. O aplicativo não compra planos. Confira preços/regras atuais de OneDrive e Tailscale diretamente nas contas; não se presume capacidade gratuita suficiente.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest -q
# Abrem câmera/microfone reais; pare o aplicativo antes:
.\.venv\Scripts\python.exe scripts\hardware_test.py
.\.venv\Scripts\python.exe scripts\reliability_test.py
```

Os testes automatizados usam diretórios temporários e dados sintéticos. Os scripts de hardware salvam mídia somente em `%LOCALAPPDATA%\SecurityWebCam-hardware-tests*` e `%LOCALAPPDATA%\SecurityWebCam-reliability-tests*`, fora do repositório. Não envie esses arquivos ao Git. Relatórios públicos contêm apenas métricas e resultados sanitizados. Veja [docs/TESTES.md](docs/TESTES.md).

## Atualização, recuperação de senha e desinstalação

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall.ps1
```

Atualização solicita encerramento local, aguarda liberação do bloqueio, recusa alterações Git não salvas, usa `git pull --ff-only` e reinstala dependências/atalhos. Se falhar, não apaga dados. Abra novamente pelo menu Iniciar. Faça backup do catálogo/configuração com o aplicativo parado antes de atualizações relevantes.

Desinstalação encerra o processo, remove o valor Run e os atalhos, preservando gravações, cópias, configuração e código. Remova a regra Serve exclusiva conforme a seção de acesso remoto. Tailscale/OneDrive são programas independentes e não são desinstalados. Depois de guardar seus dados, pode excluir manualmente a pasta do código/`.venv`; pastas de gravação e `%LOCALAPPDATA%\SecurityWebCam` são separadas. Nenhuma gravação é apagada pelo desinstalador.

Esqueceu a senha? Com acesso à sua conta Windows:

```powershell
.\.venv\Scripts\python.exe -m securitywebcam --shutdown
.\.venv\Scripts\python.exe -m securitywebcam --set-password
```

A senha é digitada de forma oculta e nunca passada na linha de comando. Reinicie pelo atalho. Erros anteriores à abertura do painel ficam em `%LOCALAPPDATA%\SecurityWebCam\startup-error.log`.
