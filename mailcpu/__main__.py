"""Allow `python -m mailcpu` to invoke the native MailCPU CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
