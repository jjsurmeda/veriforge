# Admin bootstrap runbook

How to create (or recover) the first admin on a deployed instance, and how
to check that email actually sends.

**There is no admin bootstrap endpoint, and there is not going to be one.**
An unauthenticated route that can mint an administrator is an attack surface
on the one path where being wrong gives someone the whole instance. The
bootstrap stays a script that an operator runs deliberately, over the shell,
with credentials they supply. Everything an admin can do afterwards is a
normal authenticated admin route.

## Create the admin

On the instance, as the user the app runs as:

```sh
docker compose exec -e ADMIN_EMAIL='you@example.com' \
                    -e ADMIN_PASSWORD='<strong password>' \
                    api python -m scripts.seed_admin
```

It prints one line: `created admin you@example.com (<uuid>)`, or
`promoted admin …` if the account already existed.

| variable | required | meaning |
| --- | --- | --- |
| `ADMIN_EMAIL` | yes | the admin's address |
| `ADMIN_PASSWORD` | yes | its password; the script refuses to invent one |

Why the `-e` flags rather than putting them in `.env`: these are one-time
operator credentials, not configuration. `docker compose exec -e` keeps them
out of a file that ships to every service, and the shell history entry is
the same risk as any password typed on a command line. On an instance where
shell history is a concern, read them from a file instead:

```sh
docker compose exec -T api sh -c \
  'ADMIN_EMAIL="$(cat /run/secrets/admin_email)" \
   ADMIN_PASSWORD="$(cat /run/secrets/admin_password)" \
   python -m scripts.seed_admin'
```

The script is idempotent: an existing account is promoted to `admin` and its
password re-set. That makes it the recovery path too — a rotated or lost
admin password is fixed by running it again, not by a database edit.

It talks to the database directly, like `seed_models.py` and
`seed_gutenberg.py`, because no HTTP surface can create the first admin.
That is the bootstrapping problem, not something to work around inside the
app. It never writes a plan and never touches `free` or `pro`.

Locally, `make seed-admin` does the same thing with the values from `.env`.

## Check that email actually sends

Password reset returns `202` whether or not the address has an account, and
whether or not the message went out — that is required, or the endpoint
becomes a way to enumerate users. So a broken mail configuration is silent,
which is how KI-35 survived.

Send one real message through the configured transport:

```sh
docker compose exec api python -m scripts.send_test_email --to you@example.com
```

`--to` defaults to `SMTP_FROM`, so omitting it sends to the sender address
and names nobody.

| exit | meaning | what to do |
| --- | --- | --- |
| 0 | the relay accepted the message | nothing |
| 1 | the transport was reachable but delivery failed | check the SES credentials, and that the `From` address is verified in that region |
| 2 | the configuration is unusable | see below |

On success it prints the transport, host, port and from-address it used. It
prints the host and port on purpose and never the password.

Exit 2 means the same refusal startup makes, surfaced before anything is
sent. In production the deployment would not have come up at all; locally it
means `EMAIL_TRANSPORT` is `smtp` without a usable `SMTP_HOST`/`SMTP_FROM`,
or `dev_log`, which is refused outside development on purpose.

## SES notes

`EMAIL_TRANSPORT=smtp` with `smtplib` reaches AWS SES with no new dependency
(TRD §16). SES publishes `email-smtp.<region>.amazonaws.com:587`.

The two things that fail in practice, both invisible from the app:

- **The from-address is not verified** in the region you point at. SES
  accepts the connection and rejects the envelope, so every send fails while
  the configuration looks right.
- **Credentials are scoped to one region.** SMTP credentials issued in one
  region are not accepted by another region's endpoint.

Both are exactly what `send_test_email` exists to catch, which is why it
goes over a socket rather than through a unit test.