# POSSESSION LAB Mobile

A native-feeling Expo/React Native client for the POSSESSION LAB API. One
TypeScript codebase runs on iOS and Android.

## What ships

- League Pulse with leaders, power index, and model probabilities
- player search, profiles, career arc, percentiles, and recent form
- team rooms with record, factors, rotation, games, and authorized payroll
- configurable matchup predictions
- on-device saved players and teams
- offline fallback to the last successful response
- API keys stored in iOS Keychain / Android Keystore
- accessible controls, pull-to-refresh, loading, empty, and error states

All basketball calculations stay in the FastAPI backend. The app only displays
documented JSON contracts.

## Run locally

Use Node.js 20 or newer. Start the API from the repository root:

```bash
uv run uvicorn nba_insights.api:app --host 0.0.0.0 --port 8000
```

Then start Expo:

```bash
cd mobile
npm install
npm start
```

The initial defaults are `http://127.0.0.1:8000` on iOS and
`http://10.0.2.2:8000` on the Android emulator. For a physical phone, open
Connection settings in the app and enter the computer's LAN address, for
example `http://192.168.1.20:8000`. The phone and computer must be on the same
network. Remote production servers should use HTTPS.

You can set a build-time default:

```bash
EXPO_PUBLIC_API_URL=https://analytics.example.com npm start
```

## Quality checks

```bash
npm run typecheck
npm run lint
npm test
```

## Native builds

Configure the real App Store and Play Store identifiers in `app.json`, sign in
to Expo Application Services, then:

```bash
npx eas-cli build --platform ios --profile production
npx eas-cli build --platform android --profile production
```

Internal installable builds use the `preview` profile. Store submissions use
`npx eas-cli submit --platform ios` or `--platform android` after the listing,
screenshots, privacy URLs, and signing accounts are ready.
