# Administration and shared device credentials

## Hosting computer

1. Open **Account → Administration → Create Director Account**. Choose your own username and password; Atlas ships without a default password.
2. Under **Users**, select **Create User**. Assign only the functions that engineer needs. There is no fixed four-engineer limit. New and reset passwords must be changed on the next sign-in.
3. Under **Device Credentials**, select **Add Profile**. Enter the device username/password once and list the device addresses that should use them, one per line. An address can belong to one profile. Saving a profile never changes the device itself. Reopen device tabs after changing credentials.
4. Under **Account Server**, enter this computer's local LAN IP and choose a port (default 8443). Select **Start Account Server**. Copy the server address and SHA-256 certificate fingerprint to each workstation through a trusted channel.

The server runs inside the hosting Atlas process. Keep Atlas open on that computer. Start the server again after restarting the application. No Windows service, firewall rule or automatic LAN listener is installed. The network must permit clients to reach the selected server port; this has to be arranged by the network administrator if blocked.

## Engineer workstation

1. On a fresh workstation, open **Account → Administration → Connect to Account Server**.
2. Enter the HTTPS address and the full certificate fingerprint copied from the director's server screen.
3. Sign in using the account created by the director. Change the temporary password when prompted.
4. Future launches use this server and require sign-in. The director can also sign in on a client to manage the central accounts.

Do not create an independent director account on every workstation. Each client keeps only the server address/fingerprint locally; its session token stays in memory. User records and saved device passwords remain on the server. Authenticated device passwords are transmitted over the paired TLS connection only when a permitted device web view needs them.

## Permissions and behaviour

- Network discovery/readouts, audio monitoring, audio recording, device web UI, library viewing, library downloads, events/syslog, diagnostics and Ollama have separate permissions.
- Recording requires audio monitoring; downloading requires library viewing.
- Audio-only users can choose the reception adapter through **Audio Monitor → Select Audio Network Adapter** without access to discovery.
- Configuration web access grants access to the entire device web interface. Atlas cannot enforce individual restrictions inside third-party device pages.
- Sign-out closes private device/library tabs, clears browser authentication by discarding their private profiles, stops reception/recording and clears assistant text. Active recordings are finalized.
- The client checks its central session every five seconds in a background thread. Revoked permissions stop the corresponding functions. If the server becomes unavailable, the client locks after detecting that failure. A recording or listening session therefore stops too; it does not continue under unverified permissions.
- Sessions expire after eight hours. Password resets invalidate central sessions. Five failed attempts lock that account for a minute. There is no password-recovery backdoor.
- **Audit** shows central sign-ins, account/permission changes and credential-profile operations. Workstation engineering events additionally retain the signed-in Atlas username in their local event archive. The audit is not a capture of every action performed inside a device web page.

## Protection and deployment limits

Atlas account passwords use salted PBKDF2-HMAC-SHA256 (600,000 iterations). Saved device secrets and the TLS key password use Windows DPAPI under the hosting Windows account. The TLS private key is encrypted on disk. The certificate identity is checked before sending login information; a mismatched or expired certificate is rejected. The self-signed certificate currently lasts 825 days; automatic renewal is not implemented.

The hosting Windows account, its profile and the account database/identity files must be included in the organisation's protected backup process. Simply copying DPAPI-encrypted files to another Windows account does not make them usable. There is no automatic backup or migration wizard yet. Atlas permissions do not defend against someone who controls the hosting Windows account or can modify the application/database files.

References: [Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata), [Qt private browser profiles](https://doc.qt.io/qt-6.5/qwebengineprofile.html).

## Verification scope

Automated tests exercise real Windows encryption, a real loopback HTTPS account server with independent clients, user creation/editing through Qt forms, permission revocation, offline locking, certificate mismatch rejection before login, real HTTP device authentication from saved credentials, and loss of browser authentication across sign-out. These are local fixtures, not production devices. Connectivity between separate physical workstations and the organisation's firewall rules requires deployment validation.
