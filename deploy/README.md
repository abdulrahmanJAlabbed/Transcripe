# Who transcribes

alabed.site's server is too small for a good Whisper model, so it hands the
work to stronger machines over reverse SSH tunnels. A job goes to the first
that answers and moves on if that one drops out, so any of them can be off:

| | machine | model | tunnel (on the server) |
|---|---|---|---|
| 1 | the PC, while it's on | `large-v3`, GPU | `127.0.0.1:8111` |
| 2 | the Pi, always on | `large-v3-turbo`, CPU | `127.0.0.1:8110` |
| 3 | the server itself | `base` | none |

Clients see none of this: same `/api/transcribe`, same job.

    ./deploy.sh pi     # worker + tunnel on the Pi, token and URLs to the server
    ./deploy.sh pc     # the same for this PC; run it here

Both install systemd **user** units, so check `loginctl show-user $USER -p
Linger` says yes or they stop at logout.

## One-time setup on the server

The tunnels log in as a user with no shell, whose keys may open one listener:

    sudo useradd --system --home-dir /var/lib/transcripetunnel --create-home \
        --shell /usr/sbin/nologin transcripetunnel
    # in ~transcripetunnel/.ssh/authorized_keys, one line per machine:
    restrict,port-forwarding,permitlisten="127.0.0.1:8110",permitopen="127.0.0.1:9",command="/usr/sbin/nologin" ssh-ed25519 AAAA…

`/etc/ssh/sshd_config.d/70-transcripe-tunnel.conf` reaps a dead link's listener
in 45 s instead of the box-wide 6 minutes:

    Match User transcripetunnel
        AllowTcpForwarding remote
        X11Forwarding no
        PermitTTY no
        ClientAliveInterval 15
        ClientAliveCountMax 3
