# Tales User Guide

Welcome to Tales, an AI reputation monitoring platform that tracks how your organization is represented across major AI platforms like ChatGPT, Claude, Gemini, and Perplexity.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard Overview](#dashboard-overview)
3. [Managing Your Brand](#managing-your-brand)
4. [Data Collection](#data-collection)
5. [Analytics](#analytics)
6. [Reports](#reports)
7. [Settings](#settings)
8. [Admin Functions](#admin-functions-admin-only)

---

## Getting Started

### Logging In

1. Navigate to your Tales URL
2. Sign in using the method(s) available at your organization:
   - **Email/password**: Enter your email and password, then click "Sign In"
   - **Google**: Click "Sign in with Google" and follow the Google authentication flow
   - **Microsoft**: Click "Sign in with Microsoft" and follow the Microsoft authentication flow

Your login page will show whichever authentication methods your IT team has configured. You may see one method or multiple options.

### First-Time Setup

After logging in for the first time:

1. **Create a Brand** - Go to Manage > Brands and create your first brand to monitor
2. **Add Queries** - Add questions that users might ask AI platforms about your brand
3. **Run Collection** - Collect responses from AI platforms
4. **View Analytics** - See how your brand is being represented

---

## Dashboard Overview

The Dashboard provides a quick overview of your brand's AI reputation:

- **Brand Selector** - Switch between brands if you monitor multiple
- **Key Metrics** - Summary cards showing mention rates, sentiment, and positioning
- **Recent Activity** - Latest data collection runs and analysis
- **Quick Actions** - Buttons to run collection or view detailed analytics

---

## Managing Your Brand

### Brands (Manage > Brands)

Create and manage the brands you want to monitor.

**To create a brand:**
1. Go to Manage > Brands
2. Click "Add Brand"
3. Enter the brand name and description
4. Add any alternative names or spellings
5. Click Save

**Brand Settings:**
- **Brand Name** - The primary name to track
- **Description** - Context about your brand for analysis
- **Aliases** - Alternative names, acronyms, or common misspellings

### Queries (Manage > Queries)

Queries are the questions Tales asks AI platforms. Good queries reflect what real users might ask.

**To add a query:**
1. Go to Manage > Queries
2. Click "Add Query"
3. Enter the query text
4. Select a category (optional)
5. Set priority (High, Medium, Low)
6. Click Save

**Query Best Practices:**
- Use natural language questions like real users would ask
- Include both branded queries ("What is [Brand]?") and unbranded queries ("What are the best [category] options?")
- Cover different aspects: capabilities, comparisons, recommendations, etc.

### Competitors (Manage > Competitors)

Track how competitors are mentioned alongside your brand.

**To add a competitor:**
1. Go to Manage > Competitors
2. Click "Add Competitor"
3. Enter the competitor name
4. Click Save

### Descriptors (Manage > Descriptors)

Descriptors are key terms or phrases you want to track in AI responses.

**Examples:**
- Product attributes: "innovative," "reliable," "cutting-edge"
- Industry terms: "market leader," "trusted provider"
- Specific features or capabilities

---

## Data Collection

### Running Collection (Data > Collect & Analyze)

Tales collects responses from AI platforms by sending your queries and recording the responses.

**To run collection:**
1. Go to Data > Collect & Analyze
2. Select the brand to collect for
3. Choose which AI platforms to query (ChatGPT, Claude, Gemini, Perplexity)
4. Click "Start Collection"
5. Wait for collection to complete (may take several minutes)

**Collection Notes:**
- Collection queries each platform with each of your active queries
- Responses are automatically analyzed for mentions, sentiment, and positioning
- You can schedule automatic collection (see Scheduled Tasks)

### Viewing Responses (Data > Responses)

See all collected responses and their analysis.

**Filters:**
- **Date Range** - Filter by collection date
- **Platform** - Filter by AI platform
- **Query** - Filter by specific query
- **Mention Status** - Filter by whether brand was mentioned

**Response Details:**
- Full response text from the AI platform
- Analysis results: mentioned (yes/no/indirect), sentiment, position
- Competitors mentioned
- Descriptors found

### Automated Schedule

Tales uses a fixed collection and reporting schedule for all brands. This ensures consistent data collection and timely reports.

**Data Collection Schedule:**
- Runs on the **1st, 7th, 14th, and 21st** of each month at 6:30 AM UTC
- Analysis runs automatically after each collection
- All enabled brands are collected on these dates

**Report Generation Schedule:**
- **Monthly reports**: 1st of each month at 6:00 AM UTC
- **Quarterly reports**: April 1, July 1, October 1, January 1 at 7:00 AM UTC
- **Annual reports**: January 1 at 8:00 AM UTC

**Email Notifications:**
- Emails are sent when reports are generated (not after collection/analysis)
- Ensure your email address is correct in your profile to receive notifications

**To enable/disable scheduled collection for a brand:**
1. Go to Data > Collect & Analyze
2. Toggle "Enable Automated Collection" for the brand
3. Disabled brands are skipped during scheduled runs

**Note:** Manual collection can still be run at any time from Data > Collect & Analyze.

---

## Analytics

Analytics pages help you understand how your brand is represented across AI platforms.

### Brand Mentions (Analytics > Brand Mentions)

Track how often your brand is mentioned in AI responses.

**Metrics:**
- **Mention Rate** - Percentage of queries where brand is mentioned
- **Mention Trend** - How mention rate changes over time
- **By Platform** - Comparison across AI platforms
- **By Query Type** - Branded vs. unbranded queries

### Sentiment Analysis (Analytics > Sentiment)

Understand the tone of AI responses about your brand.

**Sentiment Categories:**
- Very Positive
- Positive
- Neutral
- Negative
- Mixed

### Positioning Analysis (Analytics > Positioning)

See where your brand is positioned in AI recommendations.

**Position Categories:**
- **Leader** - Presented as the top/best option
- **Top 3** - Listed among top recommendations
- **Featured** - Mentioned prominently
- **Listed** - Mentioned but not prominently
- **Not Mentioned** - Brand not included

### Share of Voice (Analytics > Share of Voice)

Compare your brand's visibility against competitors.

**Metrics:**
- Your brand's share of total mentions
- Competitor comparison
- Platform breakdown

### Competitor Threats (Analytics > Competitor Threats)

Identify when competitors are recommended instead of your brand.

**Insights:**
- Which competitors appear most often
- Query categories where competitors dominate
- Platform-specific competitor patterns

### Descriptor Analysis (Analytics > Descriptors)

See which descriptors are associated with your brand.

**Metrics:**
- Frequency of each descriptor
- Positive vs. negative descriptors
- Trends over time

### Investigations (Analytics > Investigations)

The other analytics pages tell you *that* a number moved. An investigation works
out *why*. If your mention rate fell twelve points, an investigation determines
whether that was one platform re-ranking its answers, a competitor's PR push, a
single query flipping, or a collection run that partly failed.

**To run one:**
1. Go to Analytics > Investigations
2. Click "Investigate" to compare the most recent month against the one before it
3. Or use the dropdown arrow next to the button to compare quarters, or the
   latest collection against the previous one

An investigation takes a few minutes. The page updates on its own while one is
running, so you can leave it open.

**Reading the result:**

Each investigation is a card, newest first. Click one to expand it.

- **Summary** - what happened, in a few paragraphs, with specific numbers
- **Key findings** - the evidence, citing platforms, queries, and figures
- **Recommended actions** - what to consider doing about it
- **Limitations** - anything the investigation could not check, and what that
  means for its conclusions. This is information, not an error. An investigation
  with no web-search provider configured still runs on your collected data and
  tells you what it could not verify
- **Show agent trace** - the individual steps taken, if you want to audit how a
  conclusion was reached

**Automatic investigations.** Tales opens an investigation on its own when a
metric moves more than its threshold between two periods: 10 points for mention
rate or share of voice, 15 for positive sentiment or leadership visibility.
Competitor share of voice is watched per competitor, so a rival surging gets
explained even when your own share barely moves. These are marked "auto" and
appear alongside the ones you run yourself. Your administrator can retune or
disable them.

**A note on what this catches.** An investigation checks data quality on both
sides of the comparison before attributing anything to reputation. A batch of
unanalyzed responses is a collection failure, not a reputation drop, and the
investigation will say so rather than inventing a reputational story for it.

---

## Reports

### Generating Reports (Reports)

Create comprehensive reports of your brand's AI reputation.

**To generate a report:**
1. Go to Reports
2. Select the brand
3. Choose the date range
4. Select report sections to include
5. Click "Generate Report"

**Report Contents:**
- Executive summary
- Key metrics and trends
- Platform-by-platform analysis
- Competitor comparison

**Export Options:**
- View in browser
- Download as PDF
- Download as Word document
- Download as PowerPoint

---

## Settings

### Profile Settings

Update your account information:
- Full name
- Organization
- Email (view only)

### Password

Change your password:
1. Go to Settings
2. Enter current password
3. Enter new password
4. Confirm new password
5. Click Save

---

## Admin Functions (Admin Only)

These features are only available to users with admin privileges.

### LLM Configuration (Admin Menu > LLM Configuration)

Configure which AI platforms Tales queries for data collection.

**To access:**
1. Click your profile icon (top right)
2. Select "LLM Configuration"

**Important: Two-Part Setup Process**

Setting up LLM providers requires TWO steps, both performed by IT administrators:

**Part 1 - Environment Configuration:**
- API keys must be added to the server's `.env` file
- Example: `GEMINI_API_KEY=AIzaSy...` or `ANTHROPIC_API_KEY=sk-ant-...`
- The server must be restarted after adding keys

**Part 2 - Display Settings (This Page):**
- Configure how each provider appears in the application
- Set display name, model name, chart colors, and options
- API keys are NOT entered in this interface

**Built-in LLM Providers:**

Tales is provider-agnostic. Five `api_type` values are built in, each reading its API key from a specific environment variable:

| Provider | Environment Variable |
|----------|---------------------|
| ChatGPT (OpenAI) | `OPENAI_API_KEY` |
| Claude (Anthropic) | `ANTHROPIC_API_KEY` |
| Gemini (Google) | `GEMINI_API_KEY` |
| Perplexity | `PERPLEXITY_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` |

Only providers whose API key is configured in the environment will be available.

**Adding an LLM:**

1. Click "Add LLM"
2. Fill in the settings (NOT the API key):
   - **Display Name** - Human-readable name for charts (e.g., "Gemini", "Claude", "Azure GPT-4o")
   - **Provider Key** - Unique identifier, auto-generated from display name (e.g., "gemini", "claude", "azure_openai")
   - **API Type** - Select: OpenAI, Anthropic, Google, Azure OpenAI, or OpenAI Compatible
   - **Model Name** - The model to use (e.g., "gpt-4o", "gemini-2.0-flash", "claude-3-haiku-20240307"). For Azure OpenAI, this is the **deployment name** you created in Azure OpenAI Studio.
   - **Azure Resource URL** *(Azure only)* - e.g., `https://my-resource.openai.azure.com/`
   - **API Version** *(Azure only)* - e.g., `2024-10-21`
   - **Chart Color** - Color for this platform in charts
3. Configure options:
   - **Enabled** - Include in data collection
   - **Use for Analysis** - Designate as the analysis LLM (only one provider should have this set)
   - **Supports Web Search** - Enable for Gemini or Perplexity (these are the only providers with web search support)
4. Click "Add LLM"

**Adding Custom Providers:**

Beyond the five built-in types, admins can add custom OpenAI-compatible providers (Mistral, local models, etc.) up to a total of 6:
- **Environment Variable Name** - The env var containing the API key (e.g., "MISTRAL_API_KEY")
- **API Endpoint** - Required for OpenAI-compatible APIs

Contact your IT administrator to add the corresponding API key to the server environment before adding a custom provider.

**Notes:**
- Click "Test" to verify the API connection works
- Exactly one provider should be flagged "Use for Analysis"
- For the "State of the LLMs" report section, enable web search on Gemini or Perplexity. If no web-search-capable provider is configured (e.g., an Azure-only deployment), that section is omitted from reports; everything else works.
- Providers without valid API keys are automatically hidden

### User Management (Admin > Users)

Manage user accounts for your organization.

**To invite a new user:**
1. Go to Admin > Users
2. Click "Invite User"
3. Enter their email and name
4. Select their role (User or Admin)
5. Click Send Invitation

The invitation email adapts to how your deployment signs people in. If Google or Microsoft sign-in is configured, it tells the new user to sign in with their existing work account, and no password is involved. If your deployment uses email and password login, the email carries a personal link for setting an initial password (good for 7 days; resend the invitation to issue a fresh one). Deployments that run both get the single sign-on instruction first, with the password link offered as an alternative. If the invitation email fails to send (for example, no email service is configured), any set-password link is shown to you so you can share it directly.

**User Actions:**
- **Activate/Deactivate** - Control user access
- **Make Admin** - Grant admin privileges
- **Delete** - Remove user account

### Viewing User Activity

Admins can see:
- Active users (last 15 minutes)
- Last login times
- User's brands and data

### Managing All Brands

Admins can view and manage brands across all users.

---

## Tips for Success

### Getting Better AI Representation

1. **Use diverse queries** - Cover different ways users might ask about your topic
2. **Monitor regularly** - AI models change, so track trends over time
3. **Focus on key platforms** - Prioritize platforms your audience uses most
4. **Track competitors** - Understand the competitive landscape
5. **Act on insights** - Export the data and interpret it alongside your own strategic context

### Troubleshooting

**No data showing:**
- Make sure you've run data collection
- Check that you have active queries
- Verify the date range in filters

**Collection errors:**
- Contact your admin to verify API keys are configured in the server environment
- Some platforms may have rate limits; wait and retry

**Missing features:**
- Some features may be restricted based on your account type
- Contact your admin for access

---

## Getting Help

- Check the "How Tales Works" page in the Help menu for detailed explanations
- Contact your organization's Tales administrator
- Review this guide for feature documentation
