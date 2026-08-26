# Web Studio internationalization guide

English / [中文](/zh/guides/19-web-studio-internationalization)

Web Studio supports English and Simplified Chinese. A feature with user-visible text is complete only when both languages are usable. Add or update both translations in the same change.

## Translation resources

From the repository root, translation resources live under:

```text
web-studio/src/i18n/locales/en/
web-studio/src/i18n/locales/zh-CN/
```

`web-studio/src/i18n/locales/en.ts` and `web-studio/src/i18n/locales/zh-CN.ts` combine the module files. Put new text in the existing namespace that owns the page or feature. If a feature needs a new module, create matching English and Chinese files and register both modules in the locale entry points.

Use semantic keys that describe ownership and purpose:

```ts
settings.connection.userHint
monitoringPage.detail.columns.status
resources.retrieval.emptyTitle
```

Do not use the English sentence as the key. Do not reuse a short key when the same word has a different meaning elsewhere.

## Adding interface text

Add the key to both locale resources before using it in a component:

```ts
// web-studio/src/i18n/locales/en/workspace.ts
refresh: 'Refresh'

// web-studio/src/i18n/locales/zh-CN/workspace.ts
refresh: '刷新'
```

Use `t()` for ordinary text and component properties:

```tsx
const { t } = useTranslation('monitoringPage')

<Button aria-label={t('refresh')}>{t('refresh')}</Button>
```

Use `<Trans>` only when a sentence contains nested React elements. Keep interpolation names and their meaning identical in every locale:

```ts
updatedAt: 'Updated at {{time}}'
updatedAt: '更新于 {{time}}'
```

Do not add language branches with hard-coded phrases:

```tsx
// Do not add this pattern.
i18n.language.startsWith('zh') ? '刷新' : 'Refresh'
```

Language branches are appropriate for locale-specific behavior such as documentation URLs or date formatting, not for choosing interface copy.

## Text received from the server

Do not translate arbitrary server output. A server value may be a model name, provider value, path, URI, identifier, command, or error detail.

Prefer structured server fields. Map stable enums or protocol labels to i18n keys at the UI boundary. Keep the raw value for requests, comparisons, logs, and error handling.

When an endpoint returns display-oriented text such as an ASCII table:

1. Parse the transport format into a typed UI model.
2. Localize only allowlisted headers, metrics, statuses, and enum values.
3. Render the localized model in a component.
4. Return unknown values unchanged unless the product defines a safe display label.

The monitoring page provides the local pattern:

```text
web-studio/src/routes/monitoring/-lib/parse-status.ts
web-studio/src/routes/monitoring/-lib/localize-observer-status.ts
web-studio/src/routes/monitoring/-components/observer-status-content.tsx
```

The parser owns the wire format. The localization adapter owns the mapping from stable server tokens to i18n keys. The component owns layout. Do not copy those mappings into route components.

## What to translate

| Translate                                                  | Preserve unless the product defines a display label |
| ---------------------------------------------------------- | --------------------------------------------------- |
| Page titles, buttons, form labels, help text, empty states | API key values, protocol field names, commands      |
| Table headers and status labels intended for users         | Model names, provider values, collection names      |
| Known queue, role, metric, and enum display names          | IDs, paths, URIs, filenames, operation identifiers  |
| User-facing validation and error summaries                 | Raw error details and diagnostic payloads           |

Project terms such as `Agent`, `Root`, `Trusted`, `VikingBot`, `VLM`, and `Embedding` may remain in English when they name a product role or technical concept. Keep the same choice across pages.

## Review checklist for a new feature

Before requesting review, check the following:

- Every new user-visible phrase has an English and a Simplified Chinese entry.
- Components use `t()` or `<Trans>` instead of hard-coded language branches.
- Placeholders, plural variables, links, and technical identifiers are unchanged across locales.
- Server-provided labels use a context-aware allowlist and preserve unknown values.
- Both languages have been opened in the affected interface. Check empty, loading, success, and error states that the change can reach.
- Longer Chinese labels fit at the supported widths without hiding values or controls.
- Focused tests cover any parser or localization adapter whose mapping affects runtime output.

The configured `i18next/no-literal-string` ESLint rule warns about many JSX literals, but it does not cover every TypeScript helper, conditional expression, server response, or generated label. Treat lint as one check, not proof that a feature is fully localized.

## Validation

Run checks that match the changed scope:

```bash
cd web-studio
npx prettier --check <changed-files>
npx eslint <changed-files>
npm test -- <relevant-tests>
```

Run `npm test` and `npm run build` when the change affects shared localization code, parsing, routing, or multiple pages. Report any skipped check and the reason.

## Design references

- [i18next namespaces](https://www.i18next.com/principles/namespaces)
- [Grafana internationalization guide](https://github.com/grafana/grafana/blob/main/contribute/internationalization.md)
- [Dify i18n configuration](https://github.com/langgenius/dify/blob/main/web/i18n-config/README.md)
