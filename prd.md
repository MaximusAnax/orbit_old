## **1. Executive Summary**

A private AI system designed to capture, organize, and retrieve relational memory. The goal is to eliminate the cognitive load of maintaining a network by providing a seamless transition from a raw "brain dump" to structured, searchable intelligence.

## **2. Target Experience: "The 30-Second Aha!"**

The core metric for MVP success is a user going from **Landing Page** to **First Structured Memory** in $\le 30$ seconds.

---

## **3. Functional Requirements**

### **3.1 High-Velocity Capture (MVP Focus)**

- **Inverted Onboarding:** The landing page features a direct text/voice input field. Users interact *before* they authenticate.
- **Natural Language Processing:** AI must extract Name, Role, Company, Context, and Sentiment from unstructured text.
- **Automatic Entity Linking:** System must determine if the input refers to an existing contact or requires a new profile.
- **Structured Output Visualization:** The AI's extraction must be presented back to the user as a "Memory Card" for instant validation.

### **3.2 Intelligent Relationship Profiles**

- **Dynamic Timeline:** A chronological feed of every interaction note for a specific person.
- **Contextual Tags:** Auto-generated tags (e.g., "CMU Hackathon," "ML Infra") for easy grouping.
- **Static Metadata:** Quick-glance fields for current company and role.

### **3.3 Semantic Retrieval (Search)**

- **Natural Language Queries:** Users must be able to search by *attributes* (e.g., "People I met at TartanHacks") rather than just names.
- **Vector-Based Matching:** Search results should include conceptually relevant people, even if keywords don't match exactly.

### **3.4 The "Follow-Up" Engine (MVP version)**

- **Recency Monitoring:** A dashboard view showing contacts that are "Going Cold" based on user-defined or default intervals.
- **Non-Guilt Notifications:** Daily reminders that frame follow-ups as opportunities for connection rather than tasks.

---

## **4. MVP vs. Future Scope**

| **Feature** | **MVP (The "Relief" Layer)** | **Future (The "Action" Layer)** |
| --- | --- | --- |
| **Onboarding** | Inverted: Capture → Auth → Success. | Multi-platform sync (Google/Outlook). |
| **Data Entry** | Natural Language Text / Copy-Paste. | Voice (Whisper), Business Card OCR, iOS Share Sheet. |
| **Search** | Text-based Semantic Search. | Voice-activated search ("Who did I talk to about..."). |
| **Profiles** | Basic auto-populated info + timeline. | Social scraping, News alerts for contacts. |
| **Reminders** | Simple "Last Seen" intervals. | Context-aware suggestions (e.g., "Alex just moved to SF"). |
| **Outreach** | None (Visual relief only). | AI-generated personalized outreach drafts. |

---

## **5. User Experience & Design Philosophy**

- **Calm & Reassuring:** Use a "Soft Tech" aesthetic—muted colors, rounded corners, and fluid transitions.
- **Zero-Form Entry:** No "Create Contact" forms with 10 fields. Everything is derived from natural language.
- **The "Reveal" Animation:** Use a streaming UI to show the AI "thinking" and "extracting" to make processing time feel like value-add.

---

## **6. Success Metrics**

- **Time-to-Capture:** $< 30$ seconds for first-time users.
- **Capture Frequency:** Number of memories added per user per week.
- **Recall Success:** User finds the intended person via semantic search on the first try.

---