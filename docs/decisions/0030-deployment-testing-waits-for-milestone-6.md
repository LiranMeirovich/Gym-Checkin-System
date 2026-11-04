# 0030. Features are tested locally; deployment testing waits for milestone 6

- Status: Accepted
- Date: 2026-11-04

## Context
Phone linking (milestone 3) was the first feature on the public app, the one customers reach from the internet. Some of its behaviour depends on how it's deployed: behind a proxy the app only sees plain `http` from 127.0.0.1, so the same-origin check needs the proxy to send `X-Forwarded-Proto: https`, and the `Secure` `gym_device` cookie only works on a phone over real https (browsers make an exception for `localhost`). The plan was to check both through a `cloudflared` quick tunnel on a real phone before merging.

But hosting is still open (a free server may replace the gym PC + tunnel), and CLAUDE.md already says nothing host-specific is built until it's decided. A tunnel test now would answer a question about a setup we may never use, and it needs tools installed on the PC. A phone can't reach the PC any other way, since binding to `0.0.0.0` is forbidden.

## Options
- **Test through the tunnel in each feature**: catches proxy and https problems early. Cons: tied to a host that isn't chosen, slows every public-app feature, and needs `cloudflared` and a phone each time.
- **Test locally in features; all deployment testing in milestone 6 (Operations)**: features move faster and stay host-neutral. Cons: a proxy or https problem shows up late, at deployment.

## Decision
Features are built and tested on `127.0.0.1` only: automated tests, plus the browser on the local PC (phone-sized for customer pages). Everything that needs the real deployment moves to milestone 6, which already holds the tunnel, the services and the gym-PC setup: the chosen host or tunnel, proxy headers (`X-Forwarded-Proto`, `CF-Connecting-IP`), https and the `Secure` cookie on real iPhones and Android phones, and the edge rate limiting from decision 0029. The developer's reason: it lets us move faster and deal with all of deployment in one later stage.

## Consequences
- No feature waits on a tunnel, a host or a real phone; "done" means passing tests and working on the local PC.
- Code that depends on the deployment must say so where it lives (as `app/core/http.py` does for `X-Forwarded-Proto`) and get a follow-up in the milestone 6 section of `docs/follow-ups.md`, so milestone 6 has the full list.
- Problems found in milestone 6 may need small changes to earlier code (for example, comparing the same-origin check against a configured public hostname). These should stay in one place each, and the hard rules (never `0.0.0.0`, the cookie flags) still apply from day one.
- The public app must not go live, even for a trial, before milestone 6's checks pass.
