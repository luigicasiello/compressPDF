# ComprimiPDF

Applicazione standalone per Windows e macOS per comprimere uno o più PDF, con profili pensati per esigenze diverse e particolare attenzione alla compatibilità con i portali online.

L'identità visiva usa una mascotte illustrata ricavata dalla foto fornita per il progetto, mostrata nell'intestazione e come icona dell'applicazione.

## Profili

- **Senza perdita**: comprime e riordina i flussi del PDF senza ricampionare le immagini.
- **Compatibile portali**: comprime solo le immagini. Non sostituisce, converte o elimina i font.
- **Bilanciata**: riduce immagini e risoluzione mantenendo testo e font originali.
- **Compressione forte**: punta a file piccoli, mantenendo comunque il testo selezionabile.
- **Massima compatibilità**: converte le pagine in immagini. È la soluzione di emergenza per portali molto restrittivi, ma elimina testo ricercabile, link e moduli.

Il programma conserva sempre gli originali e crea file con suffisso `_compresso`. Se il nome esiste già, aggiunge automaticamente un numero.

## Avvio dal codice

Con Python 3.11 installato, aprire PowerShell nella cartella ed eseguire:

```powershell
.\run.ps1
```

## Creazione dell'eseguibile standalone Windows

```powershell
.\build.ps1
```

Al termine l'eseguibile portabile si trova in `dist\ComprimiPDF.exe`. Non richiede Python sul computer di destinazione.

Se la versione precedente dell'app è aperta, Windows non consente di sostituirla: la nuova build viene quindi salvata in `dist\release\ComprimiPDF.exe`.

## Firma locale Windows

Alla prima compilazione, `build.ps1` crea automaticamente un certificato autofirmato denominato **ComprimiPDF Local Publisher**, valido cinque anni. La chiave privata rimane nell'archivio certificati dell'utente Windows e non viene esportata nel progetto. Il certificato pubblico viene installato negli archivi `CurrentUser\Root` e `CurrentUser\TrustedPublisher`, quindi ogni nuovo eseguibile viene firmato e verificato con SHA-256.

La configurazione può essere eseguita anche separatamente:

```powershell
.\setup-local-signing.ps1
```

Il file pubblico esportato in `certificates\ComprimiPDF-Local-Publisher.cer` può essere installato manualmente sugli altri computer personali. Una firma autofirmata non ottiene reputazione pubblica SmartScreen e non deve essere presentata come certificato commerciale.

## Creazione della versione macOS

La build deve essere eseguita direttamente su un Mac. Sono richiesti Python 3.11 o successivo e gli strumenti da riga di comando di Xcode.

```bash
bash build-macos.sh
```

Lo script crea:

- `dist/macos/ComprimiPDF.app`, l'applicazione standalone;
- `dist/macos/ComprimiPDF.dmg`, il pacchetto da aprire e copiare in Applicazioni.

Senza ulteriori configurazioni viene applicata una firma ad-hoc, adatta all'uso personale sul Mac che compila l'app. Per la distribuzione pubblica si può impostare una firma Apple Developer ID:

```bash
MACOS_SIGN_IDENTITY="Developer ID Application: Nome (TEAMID)" bash build-macos.sh
```

Per firmare e notarizzare automaticamente il DMG, creare prima un profilo per `notarytool` nel Portachiavi e indicarlo insieme all'identità:

```bash
MACOS_SIGN_IDENTITY="Developer ID Application: Nome (TEAMID)" \
MACOS_NOTARY_PROFILE="comprimipdf-notary" \
bash build-macos.sh
```

### Compilazione online con GitHub Actions

Il workflow `.github/workflows/build-macos.yml` compila nel cloud due versioni native:

- Apple Silicon, per Mac con processore M1/M2/M3/M4 e successivi;
- Intel, per i Mac meno recenti.

Dopo aver caricato il progetto in un repository GitHub, aprire **Actions > Build macOS > Run workflow**. Al termine della compilazione, nella pagina del workflow saranno disponibili due artifact contenenti i rispettivi file `.dmg` e `.app` compressi. Il workflow parte anche automaticamente quando viene pubblicato un tag che inizia con `v`.

Le build cloud predefinite hanno una firma ad-hoc per uso locale. La distribuzione pubblica senza avvisi Gatekeeper richiede comunque un account Apple Developer, un certificato Developer ID e la notarizzazione Apple.

## Compatibilità e sicurezza

- I primi quattro profili non cambiano i font e mantengono il livello testuale.
- I PDF protetti da password non vengono elaborati.
- Prima di comprimere un PDF firmato digitalmente viene mostrato un avviso, perché qualsiasi riscrittura invalida la firma.
- Ogni risultato viene riaperto, controllato e renderizzato a bassa risoluzione prima di sostituire il file temporaneo.
- Il profilo "Massima compatibilità" va usato soltanto quando un portale rifiuta ancora il file prodotto dal profilo consigliato.

## Componenti

L'app usa PySide6 (LGPL), Pillow e PyMuPDF. PyMuPDF è distribuito con licenza AGPL/commerciale: per distribuire pubblicamente il programma occorre rispettarne i termini o acquistare una licenza commerciale. Per uso personale locale questo progetto può essere compilato e utilizzato direttamente.
