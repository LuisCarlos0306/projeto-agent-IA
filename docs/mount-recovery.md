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
4. script existente, pertencente ao usuário `root` e sem permissão de escrita para grupo/outros;
5. confirmação explícita do operador;
6. nova validação do ponto de montagem após a execução do script.

Ambiente `unknown` pode ser validado, mas não recebe opção de montagem.

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

Quando está desmontada e o script atende às regras de segurança, a interface apresenta `Solicitar montagem`. A confirmação enfileira um novo job no mesmo Redis usado pelo `agent-worker`.

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

## Permissões recomendadas do script

O script deve pertencer ao `root` e não ser gravável por grupo ou outros usuários. Exemplo esperado:

```text
-rwxr-xr-x root root /db/backup/scripts/mount.sh
```

O Agent IA bloqueia a solicitação de montagem quando o script estiver ausente, não pertencer ao `root` ou estiver gravável por grupo/outros.

Se o usuário SSH precisar de sudo sem senha, a concessão deve ser restrita ao script padrão conforme a política de sudo do ambiente. Não conceda shell administrativo genérico apenas para esta funcionalidade.
