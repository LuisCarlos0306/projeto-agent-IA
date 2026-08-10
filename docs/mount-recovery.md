# Validação e montagem preventiva de unidades

O Agent IA possui um fluxo dedicado para validar pontos de montagem de backup e, somente quando necessário, solicitar a execução controlada do script padrão de montagem.

## Regra principal

A montagem não executa comandos `mount` informados pelo operador e não aceita caminho de script pela interface.

O único script corretivo permitido neste fluxo é:

```text
/db/backup/scripts/mount.sh
```

O fluxo exige:

1. validação anterior do ponto de montagem;
2. unidade confirmada como desmontada;
3. ambiente classificado como `production`, `standby`, `monitoring` ou `training`;
4. script existente e executável;
5. script sem permissão de escrita para grupo ou outros usuários;
6. entrada real do script localizada no crontab do próprio servidor;
7. identificação de um único usuário de execução no cron;
8. confirmação explícita do operador;
9. nova validação do ponto de montagem após a execução do script.

Ambiente `unknown` pode ser validado, mas não recebe opção de montagem.

## Proprietário e usuário de execução

O proprietário do arquivo não é fixado pelo Agent IA. Cada servidor pode possuir uma configuração diferente.

Exemplos válidos:

```text
-rwxr-xr-x mssql mssql /db/backup/scripts/mount.sh
-rwxr-xr-x root  root  /db/backup/scripts/mount.sh
-rwxr-x--- oracle oinstall /db/backup/scripts/mount.sh
```

O Agent IA registra proprietário, grupo e modo do arquivo, mas utiliza o crontab do servidor para identificar quem executa a rotina atualmente.

Se o cron indicar `root`, o Agent executa:

```text
/db/backup/scripts/mount.sh
```

Se o cron indicar, por exemplo, `mssql`, o Agent executa de forma controlada:

```text
sudo -u mssql -- /db/backup/scripts/mount.sh
```

Se indicar `oracle`:

```text
sudo -u oracle -- /db/backup/scripts/mount.sh
```

O nome do usuário nunca é fornecido pela interface. Ele é descoberto no crontab do servidor no momento da validação e confirmado novamente antes da montagem.

Se o script aparecer em crons de usuários diferentes, a montagem é bloqueada para revisão manual.

## Interface

A tela dedicada fica em:

```text
/ui/mounts
```

O operador informa:

- servidor/IP;
- ponto de montagem;
- ambiente;
- porta SSH opcional.

Quando a unidade está montada, o retorno termina como `MONTADA`.

Quando está desmontada, o script está seguro e o usuário do cron foi identificado sem ambiguidade, a interface apresenta `Solicitar montagem`. A confirmação enfileira um novo job no mesmo Redis usado pelo `agent-worker`.

## Worker

O worker continua consumindo `AGENT_QUEUE_NAME`. Jobs normais seguem pelo fluxo de investigação existente; jobs `mount_validation` e `mount_recovery` são tratados pelo módulo dedicado.

Não é necessário criar outro serviço systemd nem outra fila Redis.

Depois da atualização do código, reinicie os serviços web e worker para carregar a nova instrumentação.

## Prefixos autorizados

Por padrão, a validação aceita pontos de montagem abaixo de:

```text
/mnt
/backup
/db/backup
```

É possível ajustar administrativamente usando:

```bash
AGENT_MOUNT_ALLOWED_PREFIXES=/mnt,/backup,/db/backup
```

A interface nunca altera esse valor.

## Segurança do script

O Agent IA não exige proprietário específico. Ele exige que o script:

- exista no caminho padrão;
- possua bit de execução;
- não seja gravável por grupo;
- não seja gravável por outros usuários;
- esteja referenciado no crontab do servidor;
- tenha um único usuário de execução identificável.

Permissões como `755` e `750` são aceitas. Permissões como `775`, `777` ou outras que permitam escrita por grupo/outros são bloqueadas.

A concessão de sudo do usuário SSH do Agent deve permanecer restrita. Não conceda shell administrativo genérico apenas para esta funcionalidade.
