# gunicorn settings for the PodPoll API (loaded with: gunicorn --config gunicorn.conf.py app:app)
bind = "0.0.0.0:5000"
workers = 2
accesslog = "-"          # access log to stdout => visible in kubectl logs / CloudWatch / docker logs
worker_tmp_dir = "/dev/shm"  # noqa: S108 -- heartbeat files in RAM: works with a read-only root filesystem
# gunicorn 24+ opens a control socket under $HOME/.gunicorn by default. We never use it, and a
# non-root UID with no home directory cannot create it, so switch it off.
control_socket_disable = True


def on_starting(server):
    # Runs in the master BEFORE the port is bound, so CHAOS_START_DELAY_SECONDS really
    # delays the moment the container can answer health checks.
    from app import startup_delay
    startup_delay()
