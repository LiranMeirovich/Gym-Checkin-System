# 0034. Style the existing screens before self sign-up

- Status: Accepted
- Date: 2026-11-06

## Context
Milestone 4 was planned to style every screen, admin and customer, with the `frontend-design` skill, after milestone 3 was finished. Milestone 3 still has one feature left (self sign-up on the phone). The developer needs to show the system to the gym's manager and staff now, and the plain, unstyled pages from milestones 2 and 3 don't show it well.

## Options
- **Keep the order**: finish self sign-up, then milestone 4. Cons: nothing presentable until both are done.
- **Pull the styling pass forward as its own feature**: design the look once and apply it to the screens that exist today; self sign-up and the rest of milestone 4 follow. Cons: screens built later (self sign-up, the dashboard, settings, staff, reports) must follow the new look themselves instead of being styled in one sweep.
- **Do all of milestone 4 now**: styling plus the new admin screens. Cons: a large feature that delays the demo and leaves milestone 3 unfinished in between.

## Decision
Pull milestone 4's styling pass forward as the next feature, **Styling pass**, before self sign-up.

- **In scope:** the look, designed once with the `frontend-design` skill: the shared layout and navigation, the styling approach, the Hebrew font, the colours, and shared components. It covers both React builds, admin and public, works in Hebrew right-to-left, and makes the customer pages mobile-first. It's applied to every screen that exists today: setup, lock screen, home, customers list, new customer, the customer page (plan, phones, health form, check-in dialog), prices, the health form on the desk PC, and the public link, check-in, health form and plan pages.
- **Also in scope**, because it's front-end clean-up the styling touches anyway: the shared "no connection to the server" component, one shared module for plan names, `formatShekels()` and `formatMonth()`, and one helper for role checks in React (see the milestone 4 follow-ups).
- **The gym's logo** is the starting point for the look, but it never goes in the repo (it's gym-specific, decision 0006, and the repo is public). Each install keeps it in a git-ignored `branding/` folder (`branding/logo.jpg` on the developer's PC). Both apps serve it from one fixed address, and the screens show the gym's name from settings when the file is missing. This small static-file route is the one backend change in this feature.
- **Colours** come from the logo but live as theme tokens (CSS variables) in one place, so another gym changes them in one file: a deep navy (about `#1F4F73`, the wordmark) for text, headers and primary buttons, and a lighter steel blue (about `#437AA2`, the kettlebell) for accents, on white and light-grey backgrounds. The logo's textured blue is part of the image and isn't copied in CSS.
- **Out of scope:** new screens and behaviour (the dashboard, customer search, settings, staff accounts, the activity log, role-filtered menus), any other backend change, any API or schema change, and any change to the phone flows. Those stay in milestone 4. Uploading the logo on the Settings screen (stored in the database) could replace the `branding/` folder later.
- Whether the demo needs made-up sample data (and how to create it) is decided in that feature's plan.

## Consequences
- Every later feature builds its screens with the new layout and components; `/start-feature` plans should say so.
- Milestone 4 shrinks to the new admin screens and role-filtered menus.
- The styling choices (styling approach, font, any new npm package) are decided in the feature's plan and follow decision 0010 (a dependency is added by the feature that first uses it).
