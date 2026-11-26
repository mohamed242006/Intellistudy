# Brand assets (placeholders)

No logo or background image existed in the repository or in the Figma file (docs/DESIGN_SPEC_NEW.md section 10.2:
"Raster images / illustrations / photos: None found", "Background assets: None found"). These files are
**placeholders** so the layout can be built and reviewed. They are not the final IntelliStudy brand.

| File | Used for | Replace with |
|---|---|---|
| `public/brand/intellistudy-logo.svg` | Sidebar and rail mark, auth panel, mobile app bar, chat assistant avatar, loading and empty states | The final logo mark, square artwork (SVG preferred) |
| `public/images/intellistudy-background.webp` | Auth (sign in / sign up) brand panel, behind a colour overlay that keeps text contrast | The final background image, at least 1600×1200, WebP |

Keep the same paths and every usage picks the new files up. The paths live in one place:
`design-system/brand.ts`.
