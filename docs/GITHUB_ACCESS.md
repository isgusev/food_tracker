# Доступ на push в GitHub: токен + связка ключей macOS

Git на этом Mac уже настроен хранить пароли в связке ключей (`credential.helper = osxkeychain`). Нужно только выпустить токен и один раз положить его туда. После этого `git push` (и мой, и ваш) пойдёт без запросов пароля.

## 1. Выпустить токен (fine-grained PAT)

1. GitHub → аватар → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Заполните:
   - **Token name:** `food_tracker – Claude Code`
   - **Expiration:** 90 дней (потом выпустите новый токен и повторите шаг 2)
   - **Repository access:** *Only select repositories* → `isgusev/food_tracker`
   - **Permissions → Repository permissions:**
     - **Contents:** Read and write — это push;
     - **Pull requests:** Read and write — если хотите, чтобы я открывал PR;
     - **Workflows:** Read and write — только если я буду править `.github/workflows` (CI).
     - Metadata: Read-only выставится автоматически.
3. **Generate token** → скопируйте `github_pat_…`. Токен показывается один раз.

> Не вставляйте токен в чат: он попадёт в историю переписки. Его нужно ввести только в терминале.

## 2. Положить токен в связку ключей

В **своём** терминале (Terminal.app или вкладка Terminal в приложении) выполните команду — она работает и в bash, и в zsh.
После «Токен:» вставьте токен (символы не отображаются — так и задумано) и нажмите Enter:

```bash
printf "Токен: "; read -rs GH_TOKEN; echo; printf "protocol=https\nhost=github.com\nusername=isgusev\npassword=%s\n\n" "$GH_TOKEN" | git credential approve && unset GH_TOKEN && echo "Сохранено"
```

Если раньше в связке ключей был старый пароль или токен для github.com, сначала удалите его:

```bash
printf "protocol=https\nhost=github.com\n\n" | git credential reject
```

## 3. Проверить

```bash
cd ~/Documents/projects/food_tracker && GIT_TERMINAL_PROMPT=0 git ls-remote origin HEAD
```

Если пришёл хеш коммита — чтение работает. Но репозиторий публичный, поэтому для проверки **записи** нужен пробный push (он ничего не отправляет):

```bash
cd ~/Documents/projects/food_tracker && GIT_TERMINAL_PROMPT=0 git push --dry-run origin HEAD:refs/heads/auth-check
```

`Authentication failed` или `403` — токен не сохранился или у него нет прав на запись.

Ещё можно открыть **Связку ключей** (Keychain Access) и найти там `github.com`. Запись типа «Интернет-пароль» с аккаунтом `isgusev` — это и есть токен.

## Как это работает со мной

- Я выполняю `git push` через тот же git, поэтому он берёт токен из связки ключей. Сам токен я не вижу и нигде не храню.
- Каждый push приложение Claude отдельно показывает вам на подтверждение, если вы не разрешили его заранее.
- Отозвать доступ можно в любой момент: GitHub → Settings → Developer settings → Fine-grained tokens → **Revoke**.

## Альтернатива: GitHub CLI

Если поставите `gh` (через Homebrew: `brew install gh`), можно обойтись без ручного токена: `gh auth login` → GitHub.com → HTTPS → браузерная авторизация. Затем `gh auth setup-git`. Токен `gh` тоже лежит в связке ключей, а я смогу через `gh` открывать PR и смотреть CI.
