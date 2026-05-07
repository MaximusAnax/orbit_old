## **1. System Architecture Overview**

The system follows a **Serverless Event-Driven Architecture**. We utilize a "Capture-First" flow where user input is processed in a temporary state before being committed to a permanent database upon authentication.

## **2. Technical Stack**

- **Frontend:** Next.js 14+ (App Router) on Vercel.
    - *Why:* Fast initial loads, built-in API routes, and excellent support for streaming UI.
- **Database:** Supabase (PostgreSQL) with `pgvector` extension.
    - *Why:* Handles relational data (Profiles) and vector data (Semantic Search) in one place.
- **Auth:** Supabase Auth (Google/Apple OAuth).
- **AI/LLM:** * *Extraction:* OpenAI `gpt-4o-mini` with **Structured Outputs**.
    - *Embeddings:* OpenAI `text-embedding-3-small` (1536 dimensions).
- **Styling:** Tailwind CSS + Framer Motion (for the "Magic Reveal" animations).

---

## **3. The "Inverted Onboarding" Data Flow**

### **Step 1: The Anonymous Capture (Pre-Auth)**

1. User types into a `textarea` on the landing page.
2. **State Management:** The raw text is saved to `localStorage` and a local React state.
3. **Speculative Execution:** As the user finishes typing (debounced), the frontend sends the text to `/api/extract`.
4. The API calls the LLM. The LLM returns structured JSON.
5. **The Result:** The UI shows a preview of the "Memory Card" (e.g., "Found: Alex @ Figma").

### **Step 2: The Handshake (Auth)**

1. User clicks "Save to My Memory."
2. Trigger Supabase OAuth.
3. **Post-Auth Callback:** The app retrieves the structured JSON from `localStorage` (or a temporary "Pending" table in Postgres linked by session ID).
4. The system creates the `User` and `Contact` records simultaneously.

---

## **4. Database Schema (PostgreSQL)**

### **`profiles` table**

- `id`: UUID (PK)
- `user_id`: UUID (FK to Auth)
- `full_name`: Text
- `current_org`: Text
- `job_role`: Text
- `metadata`: JSONB (links, interests, etc.)
- `created_at`: Timestamp

### **`interactions` table**

- `id`: UUID (PK)
- `profile_id`: UUID (FK)
- `user_id`: UUID (FK)
- `raw_content`: Text
- `structured_summary`: Text
- `embedding`: Vector(1536) <-- *For Semantic Search*
- `interaction_date`: Timestamp

---

## **5. Core API Endpoints**

### **`POST /api/extract`**

- **Input:** `{ raw_text: string }`
- **Logic:** Uses OpenAI SDK with `response_format: { type: "json_schema", ... }`.
- **Output:** Structured JSON containing entity details and a "suggested follow-up" window.

### **`POST /api/search`**

- **Input:** `{ query: string }`
- **Logic:**
    1. Convert `query` to a vector via OpenAI Embeddings API.
    2. Execute RPC (Remote Procedure Call) in Supabase:
    SQL
        
        `SELECT * FROM interactions 
        WHERE user_id = auth.uid()
        ORDER BY embedding <=> query_embedding 
        LIMIT 5;`
        
- **Output:** Array of matching interactions and associated profiles.

---

## **6. Performance & UX Optimizations**

### **6.1 The "Magic Reveal" Streaming**

To make the 30 seconds feel faster, we use **AI Streaming**. Instead of waiting for the full JSON, we stream the LLM response to the frontend.

- The frontend parses the partial JSON and populates the "Memory Card" in real-time.
- **User Psychology:** Seeing "Name: Alex..." appear instantly makes the wait for "Role: PM..." feel negligible.

### **6.2 Semantic Cache**

For frequent searches (e.g., "Who do I know in SF?"), we will implement a simple Redis cache (Upstash) to store the vector results for 5 minutes, reducing API costs and latency.

---

## **7. Roadmap to V2 (Post-MVP)**

1. **Contact Enrichment:** Trigger a background job to search for public social links (LinkedIn/X) based on the extracted name/company.
2. **Voice Mode:** Integrate OpenAI Whisper for "Drive-time Brain Dumps."
3. **Graph Visualization:** Using `d3.js` or `react-force-graph` to show the clusters identified by the embeddings.

---
