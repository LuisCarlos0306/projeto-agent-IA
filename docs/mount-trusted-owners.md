# Proprietários confiáveis do script de mount

O fluxo de montagem preventiva executa exclusivamente `/db/backup/scripts/mount.sh`.

O proprietário do script pode variar conforme o ambiente. Por isso, o Agent IA usa uma allowlist configurável:

```env
AGENT_MOUNT_TRUSTED_OWNERS=root,mssql
```

Regras de segurança:

- o proprietário precisa estar em `AGENT_MOUNT_TRUSTED_OWNERS`;
- o arquivo não pode ser gravável por grupo ou outros;
- o caminho do script permanece fixo em `/db/backup/scripts/mount.sh`;
- o ponto de montagem precisa estar dentro dos prefixos permitidos;
- a montagem exige validação anterior e confirmação do operador.

Exemplo aceito:

```text
-rwxr-xr-x 1 mssql mssql ... /db/backup/scripts/mount.sh
```

O modo `755` não permite escrita por grupo ou outros; apenas o proprietário `mssql` pode alterar o arquivo.
