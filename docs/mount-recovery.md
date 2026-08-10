# Validação, saúde e recuperação de unidades

O Agent IA possui um fluxo dedicado para validar pontos de montagem de backup, medir a saúde operacional do mount e, somente quando necessário, solicitar uma ação controlada.

## Regra principal

A montagem não executa comandos `mount` informados pelo operador e não aceita caminho de script pela interface.

O único script de montagem permitido neste fluxo é:

```text
/db/backup/scripts/mount.sh
```

A validação diferencia quatro estados:

- `healthy`: o ponto está montado e responde à prova de acesso dentro do timeout;
- `hanging`: o ponto consta como montado, mas a prova de acesso excede o timeout seguro;
- `degraded`: o ponto consta como montado, mas a prova funcional retorna erro;
- `unmounted`: o ponto não está registrado como montado.

A validação também coleta, quando disponível, origem, tipo de filesystem e percentual de uso.

## Mount desmontado

Quando a unidade está desmontada, o fluxo exige:

1. validação anterior do ponto de montagem;
2. unidade confirmada como desmontada;
3. ambiente classificado como `production`, `standby`, `monitoring` ou `training`;
4. script existente e executável;
5. script sem permissão de escrita para grupo ou outros usuários;
6. entrada real do script localizada no crontab do próprio servidor;
7. identificação de um único usuário de execução no cron;
8. confirmação explícita do operador;
9. nova validação do ponto de montagem e da saúde após a execução do script.

Ambiente `unknown` pode ser validado, mas não recebe opção de montagem.

## Mount Hanging

Um mount pode aparecer em `/proc`/`findmnt` como montado e ainda assim estar operacionalmente travado. Para evitar falso positivo, o Agent executa uma prova de acesso com timeout.

Quando a unidade está `hanging` e as mesmas validações de script/cron estão seguras, a interface pode oferecer:

```text
Desmontar e montar novamente
```

A remontagem exige confirmação humana e segue esta sequência:

1. revalida que o ponto continua montado e `hanging`;
2. revalida script e usuário do cron;
3. executa somente uma desmontagem normal e temporizada do ponto;
4. não usa `umount -f`;
5. não usa `umount -l`;
6. se a desmontagem falhar, estiver busy ou o ponto permanecer montado, a operação para;
7. somente após desmontar executa `/db/backup/scripts/mount.sh` no contexto do usuário identificado no cron;
8. revalida o mount e a saúde;
9. só considera sucesso quando o ponto está montado e `healthy`.

O comando de desmontagem permitido pelo fluxo dedicado é limitado ao ponto previamente validado e usa timeout para impedir bloqueio indefinido. Qualquer `mount`/`umount` genérico ou com force/lazy permanece bloqueado pela política.

## Saúde e capacidade

A saúde exibida na tela é a saúde operacional do filesystem/mount. Ela verifica se o ponto está registrado como montado e se responde a uma operação de acesso dentro do tempo seguro.

Quando o `df` responde, a interface também apresenta o percentual de uso. Uso igual ou superior a 90% é registrado como estado de atenção no histórico, mesmo que o mount esteja respondendo normalmente.

Essa saúde não representa SMART físico do disco. SMART é aplicável a dispositivos locais compatíveis e não a um NFS/CIFS visto pelo cliente; por isso deve ser tratado em módulo separado.

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

O nome do usuário nunca é fornecido pela interface. Ele é descoberto no crontab do servidor no momento da validação e confirmado novamente antes de uma alteração.

Se o script aparecer em crons de usuários diferentes, a montagem/remontagem é bloqueada para revisão manual.

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

A resposta exibe:

- estado montado/desmontado;
- saúde (`SAUDÁVEL`, `HANGING`, `DEGRADADA` ou `DESMONTADA`);
- resposta de acesso;
- uso percentual quando disponível;
- origem;
- tipo de filesystem.

Quando está desmontada e elegível, a interface apresenta `Solicitar montagem`.

Quando está montada mas `HANGING` e elegível, apresenta `Desmontar e montar novamente`.

## Worker e histórico

O worker continua consumindo `AGENT_QUEUE_NAME`. Jobs normais seguem pelo fluxo de investigação existente; jobs `mount_validation`, `mount_recovery` e `mount_remount` são tratados pelo módulo dedicado.

Não é necessário criar outro serviço systemd nem outra fila Redis.

As validações e recuperações de mount são registradas na tabela existente de investigações com confiança determinística de 100% sobre o estado observado. `Hanging`, desmontado ou uso crítico entram como atenção; mount saudável entra como saudável.

Depois da atualização do código, reinicie os serviços necessários para carregar a nova instrumentação.

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
