# Follow-up scritto

## 1. L'assunzione più importante e il suo effetto sui risultati

Il valore economico che ho assegnato a ciascun tipo di opportunità: €700 per un mutuo, €400 per una revisione di portafoglio, €70 per un conto deposito e così via. Sono numeri plausibili ma inventati, e pesano sulla classifica più di qualsiasi altra scelta.

Con i valori di default le 24 priorità alte sono solo mutui (15) e revisioni di portafoglio (9). Portando il mutuo a €200 nessun mutuo resta tra le priorità alte, e salgono avvio investimenti e revisioni. Con uno scenario diverso (mutuo €300, revisione €150, protezione €300) le priorità alte diventano soprattutto PAC (11) e protezione (10).

Quindi la risposta a "chi è commercialmente interessante" dipende in buona parte da un numero che non conosco. Per questo l'ho messo in un unico file, lo si può cambiare dall'app e il README lo dichiara come il limite principale.

L'ordinamento all'interno di un singolo prodotto (chi contattare per primo per un mutuo) è molto meno sensibile, perché lì conta la propensione e non il valore base.

## 2. La prima domanda che farei a Product / Monetisation

"Quanto vale per voi una conversione su ciascun prodotto, e state ottimizzando il ricavo dei partner nel primo anno o il valore dell'utente nel tempo?"

La prima metà serve a sostituire i miei segnaposto. La seconda cambia proprio la funzione obiettivo. Se conta il ricavo di breve, mutui e referral di consulenza dominano. Se conta il valore nel tempo, Premium e i percorsi per chi parte da zero (fondo emergenza, primi investimenti) valgono molto più di quanto dice oggi il sistema, e anche la gestione degli utenti sotto pressione finanziaria diventa un investimento e non un costo.

## 3. Dove uso l'AI e perché lì invece di logica deterministica

La uso per leggere la risposta aperta e trasformarla in dati strutturati: bisogni in una tassonomia chiusa, vincoli di contatto, fatti che l'utente dichiara su di sé. Poi la uso per scrivere i brief di segmento a partire da statistiche già calcolate.

Sul testo libero una regola funziona finché le frasi sono prevedibili. In produzione non lo saranno, per tre motivi:
- **Lingue:** gli utenti scrivono in italiano, spagnolo e francese.
- **Negazioni e sequenze:** "voglio ridurre la pressione delle rate prima di pensare a investire" contiene "investire" ma dice il contrario.
- **Vincoli di contatto:** "preferisco non essere chiamato per prodotti" non esiste in nessun campo strutturato. In questo dataset lo scrivono 7 utenti che hanno dato il consenso marketing, e un sistema a regole li avrebbe chiamati.

Per i brief, l'LLM sa scegliere cosa è rilevante per quel segmento e collegarlo al catalogo, cosa che un template fa male.

Non la uso per lo scoring, i guardrail e gli insight. Lì servono tre cose: spiegare ogni raccomandazione, riprodurla uguale e avere conteggi esatti. Per limitare i rischi l'LLM non vede mai i dati finanziari del singolo utente. Il suo output viene validato contro la tassonomia, e nei brief un controllo automatico verifica che ogni numero citato esista nei dati.

## 4. Un caso in cui il sistema produce una raccomandazione convincente ma sbagliata

FZ-0110 è un lavoratore autonomo con €60.000 di liquidità. Il sistema calcola circa €42.600 oltre il cuscinetto di sicurezza e propone un PAC. Le evidenze sembrano solide (interesse per gli investimenti, €600 risparmiati ogni mese, liquidità in eccesso) e i dati non hanno anomalie, quindi la confidenza è "alta".

La sua preoccupazione principale però è "Tax payments and cash-flow swings". Per un autonomo una parte di quella liquidità è quasi certamente tasse da versare, che il survey non chiede e il sistema non sottrae. La raccomandazione è ben argomentata e numericamente precisa, ma parte da un dato sbagliato: potrebbe spingere a investire soldi che alla prossima scadenza fiscale andranno al fisco.

Lo stesso problema, in forma diversa, riguarda gli utenti con reddito stimato. FZ-0027 ha il reddito mancante ed esce come lead mutuo a priorità alta, con un mutuo sostenibile calcolato su un reddito che è una mediana. La confidenza viene abbassata a "media", ma nella lista il lead appare comunque tra i primi.

Il rischio generale è che un testo fluente e una lista di evidenze diano l'impressione di una precisione che le stime sottostanti non hanno.

## 5. Con due giorni in più

Per prima cosa preparerei un pilota misurabile su un segmento, probabilmente "Acquisto casa in vista", che ha valore alto, timing chiaro e 21 utenti contattabili. Prevederei un gruppo di controllo e traccerei gli esiti: apertura, simulazione completata, lead inviato al broker, erogazione. È l'unico modo per capire se pesi e valori sono sensati, e oggi tutto il resto poggia su quelli.

Subito dopo costruirei un piccolo set di risposte aperte reali ed etichettate a mano, un centinaio nelle tre lingue, per misurare quanto è affidabile l'estrazione LLM. Mi concentrerei soprattutto sui vincoli di contatto, dove un errore ha conseguenze di compliance.

Se restasse tempo, aggiungerei il campo "tasse da accantonare" per gli autonomi e regole diverse per paese su mutui e previdenza.
