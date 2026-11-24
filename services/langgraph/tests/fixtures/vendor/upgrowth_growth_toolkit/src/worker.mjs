// upGrowth Growth Toolkit: remote MCP server for Google Connected Apps (Cloudflare Worker).
// Port of mcp.php. Transport: Streamable HTTP, single POST endpoint, JSON responses.
// Auth: none (public, read-only tools; no user data stored or logged). v1.2 adds 4 tools.
// Routes: upgrowth.in/connected-app/mcp  and  upgrowth.in/.well-known/google-connected-apps
const DATA = {"dataset":"Growth Moves 2026 by upGrowth","research_period":"January to September 2026","hub_url":"https://upgrowth.in/growth-moves/","editions":{"fintech":{"edition_url":"https://upgrowth.in/growth-moves/fintech/","headline":"Indian fintechs grew in 2026 by changing products, licences and distribution routes rather than buying more traffic: AI in core operations, credit on UPI, cross-border payments and acquired distribution.","moves":[{"company":"Razorpay","leader":"Harshil Mathur","date":"August 2026","move":"Launched Vulcan, a payments AI foundation model, to improve payment success rates and detect international card fraud.","source_url":"https://inc42.com/buzz/razorpay-launches-ai-foundation-model-vulcan-to-expedite-digital-payments/"},{"company":"Cashfree Payments","leader":"Reeju Datta","date":"August 2026","move":"Launched Relay, AI agents that automate cart recovery, failed payment retries and COD confirmation for small businesses.","source_url":"https://ibsintelligence.com/ibsi-news/cashfrees-relay-brings-ai-agents-to-smb-payment-operations"},{"company":"Pine Labs","leader":"B. Amrish Rau","date":"June 2026","move":"Launched P3P, a protocol that lets AI agents make UPI payments for users by extending UPI's mandate framework.","source_url":"https://www.pinelabs.com/media-analyst/the-ai-agent-can-now-pay-pine-labs-launches-p3p-indias-first-agentic-payment-protocol-built-on-upi"},{"company":"FinBox","leader":"Rajat Deshpande","date":"May 2026","move":"Launched Atlas, AI agents that run lender onboarding over WhatsApp, voice and video and assemble loan files.","source_url":"https://www.tribuneindia.com/news/business/finbox-launches-ai-platform-atlas-helping-customers-secure-loans-in-24-hours/amp"},{"company":"Kiwi","leader":"Siddharth Mehta","date":"August 2026","move":"Launched Kiwi Postpaid with YES Bank, a UPI credit line that needs no credit card.","source_url":"https://www.business-standard.com/finance/news/kiwi-broadens-upi-credit-play-with-yes-bank-partnership-postpaid-launch-126081301957_1.html"},{"company":"Scapia","leader":"Anil Goteti","date":"September 2026","move":"Added Axis Bank as a third issuer for its co-branded travel credit card to approve more customers.","source_url":"https://mediabrief.com/axis-bank-scapia-launch-co-branded-travel-credit-card/"},{"company":"Yubi","leader":"Gaurav Kumar","date":"September 2026","move":"Launched Pye, a multi-lender platform giving retail borrowers access to many lenders through 1 interface.","source_url":"https://www.prnewswire.com/in/news-releases/yubi-launches-pye-a-multi-lender-platform-for-retail-borrowers-at-global-fintech-fest-2026-302873626.html"},{"company":"PhonePe","leader":"Sameer Nigam","date":"September 2026","move":"Announced UAE operations as its first foreign market after in-principle approvals from the Central Bank of the UAE.","source_url":"https://www.business-standard.com/companies/news/phonepe-to-launch-uae-operations-in-its-first-international-market-foray-126090901423_1.html"},{"company":"Jio Payment Solutions","leader":"Kashinath Hariharan","date":"September 2026","move":"Launched cross-border payment acceptance for Indian exporters after RBI authorisation as a cross-border payment aggregator.","source_url":"https://www.business-standard.com/companies/news/jio-payment-solutions-launches-cross-border-payments-for-indian-exporters-126090900600_1.html"},{"company":"Skydo","leader":"Srivatsan Sridhar","date":"May 2026","move":"Gained GIFT City and RBI approvals for outward payments, turning export collections into a 2-way cross-border platform.","source_url":"https://entrackr.com/snippets/skydo-secures-gift-city-psp-licence-and-rbi-outward-payments-license-11854851"},{"company":"Xflow","leader":"Ashwin Bhatnagar","date":"June 2026","move":"Launched card acceptance so Indian businesses can collect card payments from overseas buyers with INR payouts.","source_url":"https://aninews.in/news/business/xflow-launches-card-payment-acceptance-for-indian-businesses-receiving-global-payments20260625154515/"},{"company":"Raise Financial Services (Dhan)","leader":"Raunak Rathi","date":"May 2026","move":"Acquired GreenLife Insurance Broking to enter insurance distribution for existing customers.","source_url":"https://entrackr.com/news/dhan-parent-raise-acquires-greenlife-to-enter-insurance-distribution-biz-11829509"},{"company":"Freo","leader":"Kunal Varma","date":"May 2026","move":"Announced plans to acquire credit marketplace IndiaLends, pending approval, to add a multi-lender user base.","source_url":"https://www.business-standard.com/content/press-releases-ani/freo-announces-strategic-acquisition-of-indialends-in-a-major-push-for-growth-126050600512_1.html"},{"company":"MobiKwik","leader":"Upasana Taku","date":"March 2026","move":"Plans to scale Soundbox and EDC device sales and extend offline merchant acceptance beyond Tier I cities.","source_url":"https://www.business-standard.com/companies/news/mobikwik-sets-eyes-on-offline-payment-acceptance-market-126031901183_1.html"}]},"ecommerce":{"edition_url":"https://upgrowth.in/growth-moves/ecommerce/","headline":"Indian e-commerce growth in 2026 came from moving the store into AI assistants, selling internal infrastructure, going vertical in quick commerce and buying distribution.","moves":[{"company":"Swiggy","leader":"Madhusudhan Rao","date":"January 2026","move":"Let customers order food, groceries and dining reservations through AI assistants such as ChatGPT, Claude and Gemini via MCP.","source_url":"https://www.swiggy.com/corporate/press-release/swiggy-now-lets-you-order-food-dineout-and-shop-on-instamart-directly-inside-chatgpt-and-claude/"},{"company":"Meesho","leader":"Sanjeev Kumar","date":"March 2026","move":"Launched Vaani, a Gen-AI voice shopping assistant for offline-first shoppers.","source_url":"https://businessnewsthisweek.com/business/meesho-launches-vaani-your-meesho-dost-indias-first-gen-ai-powered-conversational-voice-shopping-assistant/"},{"company":"Nykaa","leader":"Rajesh Uppalapati","date":"June 2026","move":"Made Nykaa Beauty and Nykaa Fashion connected apps inside ChatGPT, routing purchases to Nykaa's own app or site.","source_url":"https://www.passionateinmarketing.com/nykaa-collaborates-with-openai-to-define-the-next-era-of-ai-native-commerce-in-beauty-and-fashion/"},{"company":"GoKwik","leader":"Chirag Taneja","date":"July 2026","move":"Launched a multi-brand D2C shopping experience inside ChatGPT with PayU, from discovery to payment.","source_url":"https://www.passionateinmarketing.com/gokwik-payu-enable-indias-first-multi-brand-d2c-commerce-experience-on-chatgpt-hyphen-beardo-and-kilrr-among-the-first-brands-live/"},{"company":"Ekart (Flipkart Group)","leader":"Mani Bhushan","date":"July 2026","move":"Opened its pan-India logistics network and warehousing to MSMEs, D2C brands and enterprises.","source_url":"https://stories.flipkart.com/announcement/flipkart-opens-ekart-logistics-network-to-india-s-msm-es-and-d2-c-brands"},{"company":"Delhivery","leader":"Kapil Bharati","date":"June 2026","move":"Began selling Delhivery Maps, its internally built AI geospatial APIs, to external enterprises and developers.","source_url":"https://www.bseindia.com/xml-data/corpfiling/AttachHis/a86932d6-384f-4f6c-9ce5-d0849331482c.pdf"},{"company":"Shipsy","leader":"Soham Chokshi","date":"September 2026","move":"Launched Shipsy Brain in beta, an AI layer that lets agents make and execute logistics decisions on live orders.","source_url":"https://m.economictimes.com/ai/ai-insights/ai-focused-logistics-startup-shipsy-launches-shipsy-brain-to-power-ai-agents/articleshow/133642836.cms"},{"company":"FirstClub","leader":"Ayyappan R","date":"February 2026","move":"Expanded its quality-first grocery model to citywide coverage across Bengaluru, competing on trust rather than speed.","source_url":"https://bwretailworld.com/companies/grocery-platform-firstclub-eyes-scaling-to-70-clubhouses-within-12-months"},{"company":"Slikk","leader":"Akshay Gulati","date":"June 2026","move":"Extended fashion quick commerce into jewellery, handbags, footwear and beauty.","source_url":"https://retail.economictimes.indiatimes.com/news/e-commerce/e-tailing/slikk-targets-20-25-of-bengalurus-online-fashion-market-as-it-expands-beyond-apparel/131437557"},{"company":"ZILO","leader":"Padmakumar Pal","date":"August 2026","move":"Launched Mall-to-Home delivery from partner fashion stores in Mumbai in about 120 minutes without holding stock.","source_url":"https://retail.economictimes.indiatimes.com/news/apparel-fashion/zilo-launches-mall-to-home-model-for-faster-fashion-delivery/133150399"},{"company":"Supertails","leader":"Vineet Khanna","date":"February 2026","move":"Added 30-minute pet care delivery from partner-operated dark stores and clinics.","source_url":"https://retail.economictimes.indiatimes.com/news/health-and-beauty/pharmacy/supertails-targets-100-dark-stores-100-clinics-in-three-years-eyes-rs-1000-crore-petcare-business/133196608"},{"company":"Swish","leader":"Aniket Shah","date":"April 2026","move":"Launched 10-minute food delivery in Gurugram, its first major expansion beyond Karnataka.","source_url":"https://www.tribuneindia.com/news/gurugram/bengalurus-popular-10-minute-food-delivery-service-swish-expands-to-gurugram/"},{"company":"Udaan","leader":"Vaibhav Gupta","date":"September 2026","move":"Agreed to acquire Swiggy's LYNK retail distribution business in a share swap.","source_url":"https://indianstartupnews.com/news/b2b-e-commerce-platform-udaan-to-acquire-lynk-from-swiggy-in-rs-500-crore-deal-12503792"},{"company":"Nitro Commerce","leader":"Umair Mohammed","date":"March 2026","move":"Acquired Zodiac Labs AI to add quick commerce analytics and purchase tools for D2C brands.","source_url":"https://inc42.com/buzz/nitro-commerce-acquires-zodiac-labs-ai-to-offer-quick-commerce-analytics/"}]},"healthtech":{"edition_url":"https://upgrowth.in/growth-moves/healthtech/","headline":"Indian healthtech companies grew in 2026 by owning more of the patient journey; 7 of 13 moves were acquisitions or mergers.","moves":[{"company":"Ultrahuman","leader":"Mohit Kumar","date":"March 2026","move":"Reopened US pre-orders for a redesigned ring assembled in Texas after an import restriction.","source_url":"https://cyborg.ultrahuman.com/press-releases/ultrahuman-is-back-in-the-us-ring-pro-open-for-pre-orders"},{"company":"makeO","leader":"Arpi Mehta","date":"February 2026","move":"Agreed to acquire Singapore oral care brand Zenyum, extending its aligner business across 10 countries.","source_url":"https://inc42.com/buzz/toothsi-parent-makeo-to-acquire-singapore-based-zenyum/"},{"company":"Temple","leader":"Deepinder Goyal","date":"August 2026","move":"Agreed to acquire London longevity medicine practice Longevous.","source_url":"https://www.businesstoday.in/technology/story/deepinder-goyals-temple-acquires-london-based-longevity-medicine-firm-longevous-551824-2026-08-27"},{"company":"Healthify","leader":"Tushar Vashisht","date":"August 2026","move":"Merged with US virtual nutrition provider Berry Street to reach patients through insurance-covered care.","source_url":"https://inc42.com/buzz/khosla-ventures-backed-healthify-merges-with-us-based-berry-street/"},{"company":"PB Health","leader":"Sarbvir Singh","date":"July 2026","move":"Opened its own hospitals in Delhi-NCR with insurance approvals handled before admission.","source_url":"https://www.digitalhealthnews.com/policybazaar-s-parent-pb-fintech-forays-into-hospitals-as-pb-health-expands-integrated-insurance-healthcare-model"},{"company":"ekincare","leader":"Kiran Kalakuntla","date":"July 2026","move":"Acquired Superclaims, an AI claims platform, to sell claims processing to insurers and TPAs.","source_url":"https://businessnewsthisweek.com/business/ekincare-announces-100-acquisition-of-ai-powered-claims-adjudication-platform-superclaims/"},{"company":"Tata 1mg","leader":"Prashant Tandon","date":"January 2026","move":"Expanding a physical omnichannel store network, aiming for about 500 stores by end-2026.","source_url":"https://www.business-standard.com/companies/news/health-tech-startup-tata-1mg-eyes-500-offline-stores-by-year-end-126010801086_1.html"},{"company":"Redcliffe Labs","leader":"Aditya Kandoi","date":"August 2026","move":"Acquired Pune-based Megavision Diagnostics, entering radiology beyond pathology.","source_url":"https://www.indianpharmapost.com/healthcare/redcliffe-labs-acquires-punes-megavision-to-expand-integrated-diagnostics-network-21326"},{"company":"Vijaya Diagnostic","leader":"Suprita Reddy","date":"September 2026","move":"Agreed to buy Guwahati diagnostic centre Arya Wellness, entering North-East India.","source_url":"https://insights.dsij.in/dsijarticledetail/vijaya-diagnostic-centre-acquires-arya-wellness-centre-for-rs-46-cr-enters-assam-diagnostics-market-59516"},{"company":"CureBay","leader":"Priyadarshi Mohapatra","date":"March 2026","move":"Acquired Saveo Healthtech's pharmacy distribution business serving pharmacies across South India.","source_url":"https://medicaldialogues.in/news/industry/health-investments/curebay-acquires-saveos-pharma-distribution-arm-to-strengthen-medicine-access-across-south-india-166778"},{"company":"Orange Health Labs","leader":"Dhruv Gupta","date":"January 2026","move":"Launched a prepaid annual diagnostics plan replacing pay-per-test pricing.","source_url":"https://www.passionateinmarketing.com/orange-health-labs-launches-orange-one-a-revolutionary-initiative-that-aims-to-redefine-preventive-healthcare/"},{"company":"Eka Care","leader":"Vikalp Sahni","date":"February 2026","move":"Launched Parrotlet-a v2, a clinical speech model for Hindi and Indian English, opened through developer APIs.","source_url":"https://medicircle.in/built-for-opds-not-podcasts-eka-care-unveils-parrotleta-v2-for-realtime-hindi-indian-english-medical-transcription"},{"company":"Cloudphysician","leader":"Dhruv Joshi","date":"September 2026","move":"Launched Nightingale, a hospital video foundation model, and began expanding into the US.","source_url":"https://www.prnewswire.com/news-releases/cloudphysician-unveils-nightingale-a-visual-intelligence-foundation-model-built-for-the-hospital-room-302874041.html"}]},"saas":{"edition_url":"https://upgrowth.in/growth-moves/saas/","headline":"Indian SaaS growth in 2026 came from products that execute work rather than track it, bought capability, and new surfaces and markets.","moves":[{"company":"Zoho","leader":"Sridhar Vembu","date":"September 2026","move":"Launched a single conversational AI interface across its apps and entered vertical SaaS with 7 industry applications.","source_url":"https://www.outlookbusiness.com/corporate/zoho-launches-ai-interface-zia-chat-enters-vertical-saas-with-seven-industry-applications"},{"company":"Freshworks","leader":"Dennis Woodside","date":"May 2026","move":"Repositioned around employee experience and added a no-code AI agent studio priced per session.","source_url":"https://www.freshworks.com/pressrelease/freshworks-unveils-ai-agent-studio-in-freshservice-to-unlock-service-transformation-that-drives-compounding-business-growth/"},{"company":"Darwinbox","leader":"Jayant Paleti and Chaitanya Peddi","date":"August 2026","move":"Rebuilt its HCM platform as AI-native with Cortex and took it to the US market.","source_url":"https://newsroom.darwinbox.com/darwinbox-launches-cortex-ai-native-hcm-platform"},{"company":"Rocketlane","leader":"Srikrishnan Ganesan","date":"March 2026","move":"Launched Nitro, agents that complete billable professional services tasks inside project workflows.","source_url":"https://www.prnewswire.com/news-releases/rocketlane-launches-nitro-the-industrys-first-agentic-execution-platform-for-professional-services-302702084.html"},{"company":"Sprinto","leader":"Girish Redekar","date":"March 2026","move":"Launched autonomous compliance agents, then opened an Australian data centre.","source_url":"https://www.prnewswire.com/apac/news-releases/sprinto-launches-autonomous-trust-platformmoving-compliance-from-automated-to-autonomous-302721374.html"},{"company":"Atomicwork","leader":"Vijay Rayapati","date":"June 2026","move":"Made its AI Workforce Platform generally available, selling governed AI coworkers with defined roles and permissions.","source_url":"https://www.prnewswire.com/news-releases/atomicwork-launches-the-first-governed-ai-workforce-for-enterprise-it-302795475.html"},{"company":"Ema","leader":"Surojit Chatterjee","date":"September 2026","move":"Packaged pre-trained AI employees into HR, IT and Finance hubs.","source_url":"https://techintelpro.com/news/AI/Enterprise-AI/ema-launches-hr-it-and-finance-hub-for-ai-employees-platform"},{"company":"Facilio","leader":"Prabhu Ramachandran","date":"February 2026","move":"Launched facilities management agents that run on existing CMMS, ERP and finance systems.","source_url":"https://www.prnewswire.com/news-releases/facilio-launches-autonomous-ai-agents-to-automate-manual-back-office-work-in-facilities-management-302685168.html"},{"company":"Postman","leader":"Abhinav Asthana","date":"January 2026","move":"Acquired Fern to extend into API documentation and SDK generation.","source_url":"https://blog.postman.com/postman-acquires-fern/"},{"company":"MoEngage","leader":"Raviteja Dodda","date":"June 2026","move":"Acquired Aampe to add per-user AI decisioning above its campaign tools.","source_url":"https://www.moengage.com/in-the-news/moengage-acquires-aampe-to-bring-11-agentic-decisioning-to-b2c-marketing-teams/"},{"company":"TrueFoundry","leader":"Nikunj Bajaj","date":"June 2026","move":"Acquired UK-based Seldon AI to move its machine learning customers onto TrueFoundry's AI Gateway.","source_url":"https://www.truefoundry.com/press-room/truefoundry-acquires-seldon-ai-to-accelerate-agentic-ai-capabilities-for-enterprise-customers"},{"company":"NuPlay AI (formerly Nurix AI)","leader":"Mukesh Bansal","date":"July 2026","move":"Acquired Verloop.io to add chat automation to its voice AI platform, then rebranded.","source_url":"https://entrackr.com/snippets/mukesh-bansals-nurix-ai-acquires-enterprise-conversational-ai-company-verloopio-12148976"},{"company":"Emergent","leader":"Mukund Jha","date":"February 2026","move":"Launched a mobile app that turns a spoken idea into a working app published to app stores.","source_url":"https://www.intelligentcio.com/north-america/2026/02/18/emergent-reaches-us100-million-arr-in-eight-months-as-it-launches-mobile-app/"},{"company":"Exotel","leader":"Sachin Bhatia","date":"February 2026","move":"Took its Harmony agentic CX platform to the UAE and Saudi Arabia.","source_url":"https://channelpostmea.com/2026/02/11/exotel-unveils-harmony-an-agentic-ai-powered-customer-experience-platform-in-the-middle-east/"}]}}};

const SERVER_NAME = 'upgrowth-growth-toolkit';
const SERVER_VERSION = '1.4.2';
const DEFAULT_PROTOCOL = '2025-06-18';
const BOOKING_URL = 'https://calendar.app.google/qKL9ceeHas4K4BF19';
// Filled after Google Connected Console issues the domain token.
const VERIFICATION_TOKENS = [];

const INSTRUCTIONS = 'upGrowth Growth Toolkit answers growth marketing maths and research questions. '
  + 'Use unit_economics for CAC, LTV, LTV:CAC and payback; growth_rate for period growth, CAGR or compound monthly growth; '
  + 'roas_check for return on ad spend and break-even ROAS; ad_budget_planner to estimate the ad budget needed for a customer target; '
  + "find_growth_moves for documented 2026 growth moves by Indian companies in fintech, ecommerce, healthtech and SaaS from upGrowth's Growth Moves research, each with a source link; "
  + 'max_affordable_cac for the most a business can pay per customer or lead; period_change for YoY, MoM or simple % change; seo_roi for SEO return and break-even traffic; ai_crawler_access_check to see whether a website blocks AI crawlers in robots.txt; mdr_charges for card or payment gateway MDR, GST on it and net settlement; robots_txt_generator to write a robots.txt that allows or blocks AI crawlers by purpose; schema_generator for JSON-LD schema markup; content_seo_check for word count, keyword density and readability of pasted text; meta_tags_builder for title, description, Open Graph and Twitter tags; youtube_earnings, instagram_earnings, engagement_rate and website_ad_revenue for creator and publisher income; ytd_growth, growth_projection, ppc_forecast, customer_lifetime_value, ecommerce_metrics (AOV, conversion rate), acos_check, share_of_voice, break_even, campaign_roi and attrition_rate for business maths; '
  + 'book_strategy_call when the user asks to talk to upGrowth. All tools are read-only and store nothing; ai_crawler_access_check reads only the public robots.txt and llms.txt of the domain given.';

const J = { 'Content-Type': 'application/json', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' };
const json = (obj, status = 200, extra = {}) => new Response(JSON.stringify(obj), { status, headers: { ...J, ...extra } });
const rpcOk = (id, result) => json({ jsonrpc: '2.0', id, result });
const rpcErr = (id, code, message, status = 200) => json({ jsonrpc: '2.0', id, error: { code, message } }, status);
const toolResult = (text, structured) => ({ content: [{ type: 'text', text }], structuredContent: structured, isError: false });
const toolError = (text) => ({ content: [{ type: 'text', text }], isError: true });
const ro = () => ({ readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false });

function toolDefinitions() {
  const currency = { type: 'string', description: 'ISO currency code for display, for example INR, USD or AED. Defaults to INR.', default: 'INR' };
  return withAnnotationTitles([
    { name: 'unit_economics', title: 'Unit economics (CAC, LTV, payback)',
      description: 'Calculates customer acquisition cost (CAC), customer lifetime value (LTV), the LTV to CAC ratio and CAC payback in months from spend, new customers, revenue per customer, gross margin and churn.',
      inputSchema: { type: 'object', properties: {
        acquisition_spend: { type: 'number', minimum: 0, description: 'Total sales and marketing spend for the period, in currency units.' },
        new_customers: { type: 'integer', minimum: 1, description: 'New paying customers acquired in the same period.' },
        monthly_revenue_per_customer: { type: 'number', minimum: 0, description: 'Average revenue per customer per month (ARPU), in currency units.' },
        gross_margin_pct: { type: 'number', minimum: 0, maximum: 100, description: 'Gross margin as a percentage, for example 70.' },
        monthly_churn_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of customers lost per month as a percentage, for example 3.' },
        currency }, required: ['acquisition_spend', 'new_customers', 'monthly_revenue_per_customer', 'gross_margin_pct', 'monthly_churn_pct'] },
      annotations: ro() },
    { name: 'growth_rate', title: 'Growth rate (period, CAGR, CMGR)',
      description: 'Calculates total growth and compound growth per period between a start and end value, for example month on month, quarter on quarter or year on year (CAGR).',
      inputSchema: { type: 'object', properties: {
        start_value: { type: 'number', exclusiveMinimum: 0, description: 'Value at the start, for example revenue or users.' },
        end_value: { type: 'number', minimum: 0, description: 'Value at the end.' },
        periods: { type: 'number', exclusiveMinimum: 0, description: 'Number of periods between start and end, for example 12.' },
        period_type: { type: 'string', enum: ['month', 'quarter', 'year'], description: 'Length of 1 period.', default: 'month' } },
        required: ['start_value', 'end_value', 'periods'] },
      annotations: ro() },
    { name: 'roas_check', title: 'ROAS and break-even ROAS',
      description: 'Calculates return on ad spend from ad revenue and ad spend, and the break-even ROAS implied by gross margin, then says whether the campaign covers its product cost.',
      inputSchema: { type: 'object', properties: {
        ad_revenue: { type: 'number', minimum: 0, description: 'Revenue attributed to the ads, in currency units.' },
        ad_spend: { type: 'number', exclusiveMinimum: 0, description: 'Ad spend for the same period, in currency units.' },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Gross margin as a percentage.' },
        currency }, required: ['ad_revenue', 'ad_spend', 'gross_margin_pct'] },
      annotations: ro() },
    { name: 'ad_budget_planner', title: 'Ad budget planner',
      description: 'Estimates the monthly ad budget needed to reach a target number of new customers from cost per click, landing page conversion rate and lead to customer rate.',
      inputSchema: { type: 'object', properties: {
        target_customers: { type: 'integer', minimum: 1, description: 'New customers wanted per month.' },
        cost_per_click: { type: 'number', exclusiveMinimum: 0, description: 'Expected average cost per click, in currency units.' },
        click_to_lead_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of clicks that become leads, as a percentage.' },
        lead_to_customer_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of leads that become customers, as a percentage.' },
        currency }, required: ['target_customers', 'cost_per_click', 'click_to_lead_pct', 'lead_to_customer_pct'] },
      annotations: ro() },
    { name: 'find_growth_moves', title: 'Find Growth Moves research',
      description: "Returns documented 2026 growth moves by Indian companies from upGrowth's Growth Moves research (January to September 2026), filtered by sector, company or keyword. Each move includes the leader, date and a link to the original source.",
      inputSchema: { type: 'object', properties: {
        sector: { type: 'string', enum: ['fintech', 'ecommerce', 'healthtech', 'saas', 'any'], description: 'Sector to search. Use any to search all sectors.', default: 'any' },
        company: { type: 'string', description: 'Optional company name to match, for example Razorpay.' },
        keyword: { type: 'string', description: 'Optional keyword to match in the move description, for example acquisition, UPI or AI agents.' },
        limit: { type: 'integer', minimum: 1, maximum: 14, description: 'Maximum moves to return.', default: 5 } } },
      annotations: ro() },
    { name: 'max_affordable_cac', title: 'Maximum affordable CAC and cost per lead',
      description: 'Works back from customer lifetime value to the most a business can pay to acquire a customer (and, optionally, a lead) while keeping a target LTV to CAC ratio, 3:1 by default.',
      inputSchema: { type: 'object', properties: {
        monthly_revenue_per_customer: { type: 'number', exclusiveMinimum: 0, description: 'Average revenue per customer per month (ARPU), in currency units.' },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Gross margin as a percentage.' },
        monthly_churn_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of customers lost per month as a percentage.' },
        target_ltv_to_cac: { type: 'number', exclusiveMinimum: 0, description: 'Target LTV to CAC ratio, for example 3 for 3:1.', default: 3 },
        lead_to_customer_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Optional. Share of leads that become customers, to work out the maximum cost per lead.' },
        currency }, required: ['monthly_revenue_per_customer', 'gross_margin_pct', 'monthly_churn_pct'] },
      annotations: ro() },
    { name: 'period_change', title: 'YoY, MoM or % change',
      description: 'Calculates the simple percentage change between 2 values, such as year over year (YoY), month over month (MoM), quarter over quarter or week over week, including sales or revenue growth and percentage increase or decrease.',
      inputSchema: { type: 'object', properties: {
        previous_value: { type: 'number', description: 'Value in the earlier period.' },
        current_value: { type: 'number', description: 'Value in the later period.' },
        comparison: { type: 'string', enum: ['yoy', 'mom', 'qoq', 'wow', 'custom'], description: 'Which comparison this is, used only for labelling.', default: 'custom' } },
        required: ['previous_value', 'current_value'] },
      annotations: ro() },
    { name: 'seo_roi', title: 'SEO ROI',
      description: 'Estimates the monthly return on an SEO investment from extra organic visits, conversion rate, value per conversion and monthly SEO cost, plus the break-even traffic gain.',
      inputSchema: { type: 'object', properties: {
        monthly_organic_visits_gain: { type: 'number', minimum: 0, description: 'Extra organic visits per month expected from SEO.' },
        conversion_rate_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of visits that convert, as a percentage.' },
        value_per_conversion: { type: 'number', minimum: 0, description: 'Average revenue per conversion (order value or deal value), in currency units.' },
        monthly_seo_cost: { type: 'number', exclusiveMinimum: 0, description: 'Monthly SEO spend, in currency units.' },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Optional gross margin as a percentage. Leave out to measure on revenue.' },
        months: { type: 'number', exclusiveMinimum: 0, description: 'Months to total over.', default: 12 },
        currency }, required: ['monthly_organic_visits_gain', 'conversion_rate_pct', 'value_per_conversion', 'monthly_seo_cost'] },
      annotations: ro() },
    { name: 'ai_crawler_access_check', title: 'AI crawler access check',
      description: "Reads a website's public robots.txt and llms.txt and reports whether AI crawlers from OpenAI, Anthropic, Perplexity and Google (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended and others) are allowed, restricted or blocked.",
      inputSchema: { type: 'object', properties: {
        domain: { type: 'string', description: 'Public domain to check, for example example.com.' } }, required: ['domain'] },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true } },
    { name: 'mdr_charges', title: 'MDR charges calculator',
      description: 'Calculates merchant discount rate (MDR) charges on card or payment gateway sales: the MDR fee, GST on that fee, total cost, effective rate and net settlement. Uses the MDR % the user gives; it does not look up provider rates.',
      inputSchema: { type: 'object', properties: {
        sales_value: { type: 'number', exclusiveMinimum: 0, description: 'Total value of the transactions, in currency units.' },
        mdr_pct: { type: 'number', minimum: 0, maximum: 100, description: 'MDR or TDR charged by the provider, as a percentage, for example 1.8.' },
        transactions: { type: 'integer', minimum: 1, description: 'Optional. Number of transactions, needed only with a fixed fee per transaction.' },
        fixed_fee_per_transaction: { type: 'number', minimum: 0, description: 'Optional fixed fee per transaction, in currency units.' },
        gst_pct: { type: 'number', minimum: 0, maximum: 100, description: 'GST charged on the MDR fee, as a percentage.', default: 18 },
        currency }, required: ['sales_value', 'mdr_pct'] },
      annotations: ro() },
    { name: 'robots_txt_generator', title: 'robots.txt generator for AI crawlers',
      description: 'Writes a robots.txt file that allows or blocks AI crawlers by purpose: model training (GPTBot, ClaudeBot, Google-Extended), AI search (OAI-SearchBot, Claude-SearchBot, PerplexityBot) and user-triggered fetches (ChatGPT-User, Claude-User, Perplexity-User), plus paths to keep private and a sitemap. Never blocks Googlebot.',
      inputSchema: { type: 'object', properties: {
        ai_training: { type: 'string', enum: ['allow', 'block'], description: 'Whether AI model training crawlers may crawl the site.', default: 'allow' },
        ai_search: { type: 'string', enum: ['allow', 'block'], description: 'Whether AI search crawlers may crawl the site.', default: 'allow' },
        ai_user_fetch: { type: 'string', enum: ['allow', 'block'], description: 'Whether assistants may fetch pages when a user asks about them.', default: 'allow' },
        disallow_paths: { type: 'array', items: { type: 'string' }, maxItems: 20, description: 'Optional paths to keep out of all crawlers, each starting with /, for example /wp-admin/.' },
        sitemap_url: { type: 'string', description: 'Optional full sitemap URL, for example https://example.com/sitemap.xml.' } } },
      annotations: ro() },
    { name: 'schema_generator', title: 'Schema markup (JSON-LD) generator',
      description: 'Builds valid schema.org JSON-LD for a page: FAQ, local business, organization, article or blog post, product, person or breadcrumb. Checks the properties Google lists as required for that type (per Google Search Central structured data docs, developers.google.com/search/docs/appearance/structured-data) and returns a ready-to-paste script tag.',
      inputSchema: { type: 'object', properties: {
        schema_type: { type: 'string', enum: ['faq', 'local_business', 'organization', 'article', 'product', 'person', 'breadcrumb'], description: 'Which schema to build.' },
        data: { type: 'object', description: 'Fields for that type. faq: questions [{question, answer}]. local_business: name, business_type (for example Dentist), address {street, locality, region, postal_code, country}, telephone, url, image, price_range, geo {latitude, longitude}, opening_hours [{days: [Monday...], opens: "09:00", closes: "18:00"}]. organization: name, organization_type, url, logo, description, legal_name, founding_date, email, telephone, same_as [urls], address. article: headline, article_type (Article, BlogPosting or NewsArticle), url, images [urls], date_published, date_modified, authors [{name, url, job_title}], publisher {name, logo}. product: name, description, images, brand, sku, price, currency, availability (InStock, OutOfStock, PreOrder, SoldOut), price_valid_until, rating_value, review_count. person: name, url, job_title, works_for, image, description, same_as. breadcrumb: items [{name, url}].' } },
        required: ['schema_type', 'data'] },
      annotations: ro() },
    { name: 'content_seo_check', title: 'Content SEO check (word count, keyword density, readability)',
      description: 'Analyses text the user pastes: word, sentence and paragraph counts, reading time, approximate Flesch reading ease, long sentences and paragraphs, headings found, and focus keyword count, density and placement. Counts exactly, which assistants often get wrong.',
      inputSchema: { type: 'object', properties: {
        text: { type: 'string', description: 'The article or page text, plain text, Markdown or HTML. Up to 60,000 characters.' },
        keyword: { type: 'string', description: 'Optional focus keyword or phrase.' },
        secondary_keywords: { type: 'array', items: { type: 'string' }, maxItems: 10, description: 'Optional extra keywords to count.' } },
        required: ['text'] },
      annotations: ro() },
    { name: 'meta_tags_builder', title: 'Meta tags builder (title, description, Open Graph, Twitter card)',
      description: 'Builds the HTML head tags for a page: title, meta description, canonical, Open Graph and Twitter card tags, with character counts and truncation warnings.',
      inputSchema: { type: 'object', properties: {
        title: { type: 'string', description: 'Page title.' },
        description: { type: 'string', description: 'Meta description.' },
        url: { type: 'string', description: 'Canonical page URL.' },
        image_url: { type: 'string', description: 'Optional share image URL.' },
        site_name: { type: 'string', description: 'Optional site or brand name.' },
        twitter_handle: { type: 'string', description: 'Optional X (Twitter) handle, for example @upgrowth.' },
        page_type: { type: 'string', enum: ['website', 'article'], default: 'website', description: 'Open Graph type.' } },
        required: ['title', 'description', 'url'] },
      annotations: ro() },
    { name: 'youtube_earnings', title: 'YouTube earnings and watch hours calculator',
      description: 'Estimates YouTube ad earnings from monthly views and the RPM from YouTube Studio (or CPM, monetized playback % and the 55% long-form creator share), plus watch hours against the YouTube Partner Program threshold.',
      inputSchema: { type: 'object', properties: {
        monthly_views: { type: 'number', exclusiveMinimum: 0, description: 'Views per month on long-form videos.' },
        rpm: { type: 'number', minimum: 0, description: 'Revenue per 1,000 views from YouTube Studio, in currency units. Use this or cpm.' },
        cpm: { type: 'number', minimum: 0, description: 'Ad CPM, in currency units. Needs monetized_playback_pct.' },
        monetized_playback_pct: { type: 'number', minimum: 0, maximum: 100, description: 'Share of views that show an ad, as a percentage.' },
        avg_view_duration_minutes: { type: 'number', minimum: 0, description: 'Optional average view duration in minutes, to work out watch hours.' },
        subscribers: { type: 'integer', minimum: 0, description: 'Optional subscriber count.' },
        currency }, required: ['monthly_views'] },
      annotations: ro() },
    { name: 'instagram_earnings', title: 'Instagram creator earnings calculator',
      description: 'Estimates monthly and yearly Instagram brand-deal income from the rates the user charges per post, per story or per 1,000 followers, and the cost per engagement a brand pays.',
      inputSchema: { type: 'object', properties: {
        followers: { type: 'integer', minimum: 1, description: 'Follower count.' },
        posts_per_month: { type: 'number', minimum: 0, description: 'Sponsored posts or reels per month.' },
        rate_per_post: { type: 'number', minimum: 0, description: 'Fee per sponsored post, in currency units. Use this or rate_per_1000_followers.' },
        rate_per_1000_followers: { type: 'number', minimum: 0, description: 'Fee per post per 1,000 followers, in currency units.' },
        stories_per_month: { type: 'number', minimum: 0, description: 'Optional sponsored stories per month.' },
        rate_per_story: { type: 'number', minimum: 0, description: 'Optional fee per story.' },
        avg_engagements_per_post: { type: 'number', minimum: 0, description: 'Optional average likes plus comments plus saves plus shares per post.' },
        currency }, required: ['followers', 'posts_per_month'] },
      annotations: ro() },
    { name: 'engagement_rate', title: 'Engagement rate calculator',
      description: 'Calculates social media engagement rate for Instagram, YouTube, LinkedIn or any platform from likes, comments, shares and saves, by followers, reach, impressions or views.',
      inputSchema: { type: 'object', properties: {
        likes: { type: 'number', minimum: 0 }, comments: { type: 'number', minimum: 0 },
        shares: { type: 'number', minimum: 0 }, saves: { type: 'number', minimum: 0 },
        base_type: { type: 'string', enum: ['followers', 'reach', 'impressions', 'views'], default: 'followers', description: 'What to divide by.' },
        base_value: { type: 'number', exclusiveMinimum: 0, description: 'Followers, reach, impressions or views.' },
        posts: { type: 'integer', minimum: 1, default: 1, description: 'Number of posts the totals cover.' } },
        required: ['base_value'] },
      annotations: ro() },
    { name: 'website_ad_revenue', title: 'Website ad revenue (AdSense) calculator',
      description: 'Estimates display ad revenue for a website or blog from monthly pageviews and page RPM, or from ad impressions per page, CPM and fill rate.',
      inputSchema: { type: 'object', properties: {
        monthly_pageviews: { type: 'number', exclusiveMinimum: 0 },
        page_rpm: { type: 'number', minimum: 0, description: 'Earnings per 1,000 pageviews (from AdSense reports), in currency units. Use this or cpm.' },
        ads_per_page: { type: 'number', minimum: 0, description: 'Ad units per page, used with cpm.' },
        cpm: { type: 'number', minimum: 0, description: 'Earnings per 1,000 ad impressions, in currency units.' },
        fill_rate_pct: { type: 'number', minimum: 0, maximum: 100, default: 100, description: 'Share of ad requests filled.' },
        currency }, required: ['monthly_pageviews'] },
      annotations: ro() },
    { name: 'ytd_growth', title: 'Year-to-date (YTD) growth calculator',
      description: 'Compares year-to-date totals with the same period last year, from monthly values or YTD totals, and gives a simple full-year run rate.',
      inputSchema: { type: 'object', properties: {
        this_year_monthly: { type: 'array', items: { type: 'number' }, maxItems: 12, description: 'This year\'s values by month so far, January first (or first month of the financial year).' },
        last_year_monthly: { type: 'array', items: { type: 'number' }, maxItems: 12, description: 'Last year\'s values for the same months.' },
        this_ytd_total: { type: 'number', description: 'Alternative: this year\'s YTD total.' },
        last_ytd_total: { type: 'number', description: 'Alternative: last year\'s total for the same period.' },
        months_elapsed: { type: 'integer', minimum: 1, maximum: 12, description: 'Months covered, needed with totals for the run rate.' } } },
      annotations: ro() },
    { name: 'ppc_forecast', title: 'PPC and Google Ads forecast',
      description: 'Forecasts a paid search or social budget: clicks, conversions, cost per acquisition, revenue, ROAS, profit after ad spend and break-even CPA, from budget, CPC and conversion rate.',
      inputSchema: { type: 'object', properties: {
        monthly_budget: { type: 'number', exclusiveMinimum: 0 },
        cost_per_click: { type: 'number', exclusiveMinimum: 0 },
        conversion_rate_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Share of clicks that convert.' },
        value_per_conversion: { type: 'number', minimum: 0, description: 'Optional revenue per conversion.' },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Optional gross margin for profit and break-even CPA.' },
        currency }, required: ['monthly_budget', 'cost_per_click', 'conversion_rate_pct'] },
      annotations: ro() },
    { name: 'customer_lifetime_value', title: 'Customer lifetime value (repeat purchase)',
      description: 'Calculates customer lifetime value for repeat-purchase businesses such as D2C and ecommerce from average order value, purchases per year, lifespan and margin, with optional discounting and LTV to CAC.',
      inputSchema: { type: 'object', properties: {
        average_order_value: { type: 'number', exclusiveMinimum: 0 },
        purchases_per_year: { type: 'number', exclusiveMinimum: 0 },
        customer_lifespan_years: { type: 'number', exclusiveMinimum: 0 },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100 },
        annual_discount_rate_pct: { type: 'number', minimum: 0, maximum: 100, description: 'Optional, to discount future years.' },
        cac: { type: 'number', exclusiveMinimum: 0, description: 'Optional customer acquisition cost.' },
        currency }, required: ['average_order_value', 'purchases_per_year', 'customer_lifespan_years', 'gross_margin_pct'] },
      annotations: ro() },
    { name: 'ecommerce_metrics', title: 'Ecommerce metrics (AOV, conversion rate, revenue per visitor)',
      description: 'Calculates average order value, conversion rate, revenue per visitor and orders per customer, and the sessions needed to hit a revenue target.',
      inputSchema: { type: 'object', properties: {
        revenue: { type: 'number', minimum: 0 }, orders: { type: 'integer', minimum: 1 },
        sessions: { type: 'number', exclusiveMinimum: 0, description: 'Optional sessions or visitors in the same period.' },
        customers: { type: 'integer', minimum: 1, description: 'Optional unique customers.' },
        target_revenue: { type: 'number', exclusiveMinimum: 0, description: 'Optional revenue goal for the same period length.' },
        currency }, required: ['revenue', 'orders'] },
      annotations: ro() },
    { name: 'growth_projection', title: 'Growth and revenue projection',
      description: 'Projects a value forward at a compound growth rate per period (exponential growth), shows each period, the doubling time and how long it takes to reach a target.',
      inputSchema: { type: 'object', properties: {
        start_value: { type: 'number', exclusiveMinimum: 0 },
        growth_rate_pct: { type: 'number', exclusiveMinimum: -100, description: 'Growth per period as a percentage; negative for decline.' },
        periods: { type: 'integer', minimum: 1, maximum: 120 },
        period_type: { type: 'string', enum: ['month', 'quarter', 'year'], default: 'month' },
        target_value: { type: 'number', exclusiveMinimum: 0, description: 'Optional target to reach.' } },
        required: ['start_value', 'growth_rate_pct', 'periods'] },
      annotations: ro() },
    { name: 'acos_check', title: 'Amazon ACoS, TACoS and break-even ACoS',
      description: 'Calculates Amazon advertising cost of sales (ACoS), ROAS, break-even ACoS from margin, profit after ads, and TACoS against total sales.',
      inputSchema: { type: 'object', properties: {
        ad_spend: { type: 'number', exclusiveMinimum: 0 }, ad_sales: { type: 'number', exclusiveMinimum: 0 },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Optional margin before ad costs.' },
        total_sales: { type: 'number', exclusiveMinimum: 0, description: 'Optional total sales including organic, for TACoS.' },
        currency }, required: ['ad_spend', 'ad_sales'] },
      annotations: ro() },
    { name: 'share_of_voice', title: 'Share of voice calculator',
      description: 'Calculates share of voice for a brand against competitors on any metric: AI assistant citations or mentions, search impressions, ad impressions, social mentions or press coverage.',
      inputSchema: { type: 'object', properties: {
        brand_name: { type: 'string' }, brand_value: { type: 'number', minimum: 0 },
        competitors: { type: 'array', maxItems: 20, items: { type: 'object', properties: { name: { type: 'string' }, value: { type: 'number', minimum: 0 } }, required: ['name', 'value'] } },
        metric: { type: 'string', description: 'What was counted, for example ChatGPT citations or impressions.' } },
        required: ['brand_name', 'brand_value', 'competitors'] },
      annotations: ro() },
    { name: 'break_even', title: 'Break-even calculator',
      description: 'Calculates break-even units and revenue from fixed costs, price and variable cost per unit, the contribution margin, and units needed for a target profit.',
      inputSchema: { type: 'object', properties: {
        fixed_costs: { type: 'number', minimum: 0 }, price_per_unit: { type: 'number', exclusiveMinimum: 0 },
        variable_cost_per_unit: { type: 'number', minimum: 0 },
        target_profit: { type: 'number', minimum: 0, description: 'Optional profit goal.' },
        currency }, required: ['fixed_costs', 'price_per_unit', 'variable_cost_per_unit'] },
      annotations: ro() },
    { name: 'campaign_roi', title: 'Marketing campaign ROI',
      description: 'Calculates ROI for a marketing campaign or channel (content, email, events, influencer, recruitment marketing) on revenue and on gross profit.',
      inputSchema: { type: 'object', properties: {
        cost: { type: 'number', exclusiveMinimum: 0, description: 'Total campaign cost.' },
        attributed_revenue: { type: 'number', minimum: 0 },
        gross_margin_pct: { type: 'number', exclusiveMinimum: 0, maximum: 100, description: 'Optional margin for profit-based ROI.' },
        campaign_name: { type: 'string', description: 'Optional label.' },
        currency }, required: ['cost', 'attributed_revenue'] },
      annotations: ro() },
    { name: 'attrition_rate', title: 'Attrition and churn rate calculator',
      description: 'Calculates employee attrition or customer churn rate for a period from separations and headcount at the start and end, with a simple annualised rate.',
      inputSchema: { type: 'object', properties: {
        separations: { type: 'number', minimum: 0, description: 'People or customers who left in the period.' },
        headcount_start: { type: 'number', minimum: 0 }, headcount_end: { type: 'number', minimum: 0 },
        period_months: { type: 'number', exclusiveMinimum: 0, maximum: 12, default: 1 } },
        required: ['separations', 'headcount_start', 'headcount_end'] },
      annotations: ro() },
    { name: 'book_strategy_call', title: 'Book a strategy call with upGrowth',
      description: 'Returns the link to book a free 30-minute growth strategy call with upGrowth. Use only when the user asks to speak with upGrowth.',
      inputSchema: { type: 'object', properties: {} }, annotations: ro() },
  ]);
}

// Mirror each tool title into annotations.title (MCP ToolAnnotations) for directories that read it there.
function withAnnotationTitles(tools) {
  return tools.map((t) => ({ ...t, annotations: { title: t.title, ...t.annotations } }));
}

const num = (a, k) => { const v = a[k]; if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const fmt = (v, d) => Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const trimNum = (v, d) => { let s = fmt(v, d); if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, ''); return s; };
function money(v, cur) {
  const dec = Math.abs(v) >= 100 ? 0 : 2;
  if (cur !== 'INR') return cur + ' ' + fmt(v, dec);
  const neg = v < 0 ? '-' : '';
  const [intPart, frac] = Math.abs(v).toFixed(dec).split('.');
  let int = intPart;
  if (int.length > 3) { const last3 = int.slice(-3); const rest = int.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ','); int = rest + ',' + last3; }
  return 'Rs ' + neg + int + (frac !== undefined ? '.' + frac : '');
}
const cur = (a) => { const c = typeof a.currency === 'string' ? a.currency.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase() : 'INR'; return c || 'INR'; };
const r2 = (v) => Math.round(v * 100) / 100;
const r1 = (v) => Math.round(v * 10) / 10;

function tUnit(a) {
  const spend = num(a, 'acquisition_spend'), n = num(a, 'new_customers'), arpu = num(a, 'monthly_revenue_per_customer'), gm = num(a, 'gross_margin_pct'), churn = num(a, 'monthly_churn_pct'), c = cur(a);
  if ([spend, n, arpu, gm, churn].some((x) => x === null)) return toolError('Missing a required number.');
  if (n < 1 || churn <= 0 || churn > 100 || gm < 0 || gm > 100 || spend < 0 || arpu < 0) return toolError('Check the inputs: customers must be at least 1, churn between 0 and 100, margin between 0 and 100.');
  const cac = spend / n, gp = arpu * gm / 100, life = 100 / churn, ltv = gp * life;
  const ratio = cac > 0 ? ltv / cac : null, payback = gp > 0 ? cac / gp : null;
  const band = ratio === null ? 'CAC is zero, so the ratio is not meaningful.' : ratio >= 3 ? 'At or above the common 3:1 rule of thumb.' : ratio >= 1 ? 'Positive but below the common 3:1 rule of thumb.' : 'Below 1:1, so each customer costs more to acquire than it returns in gross profit.';
  const text = `CAC: ${money(cac, c)}\nLTV (gross margin basis): ${money(ltv, c)} over about ${life.toFixed(1)} months\nLTV:CAC: ${ratio === null ? 'n/a' : fmt(ratio, 2) + ':1'}\nCAC payback: ${payback === null ? 'never (no gross profit per month)' : fmt(payback, 1) + ' months'}\n${band} Rules of thumb vary by business model and stage.`;
  return toolResult(text, { currency: c, cac: r2(cac), ltv: r2(ltv), customer_lifetime_months: r1(life), ltv_to_cac: ratio === null ? null : r2(ratio), payback_months: payback === null ? null : r1(payback), assessment: band });
}
function tGrowth(a) {
  const s = num(a, 'start_value'), e = num(a, 'end_value'), p = num(a, 'periods');
  const type = ['month', 'quarter', 'year'].includes(a.period_type) ? a.period_type : 'month';
  if (s === null || e === null || p === null || s <= 0 || e < 0 || p <= 0) return toolError('Start must be above 0, end 0 or more, periods above 0.');
  const total = (e / s - 1) * 100, cg = (Math.pow(e / s, 1 / p) - 1) * 100;
  const label = { month: 'Compound monthly growth rate (CMGR)', quarter: 'Compound quarterly growth rate', year: 'Compound annual growth rate (CAGR)' }[type];
  return toolResult(`Total change: ${fmt(total, 2)}%\n${label}: ${fmt(cg, 2)}% per ${type} over ${trimNum(p, 2)} ${type}s`, { total_growth_pct: r2(total), compound_growth_pct_per_period: r2(cg), period_type: type });
}
function tRoas(a) {
  const r = num(a, 'ad_revenue'), s = num(a, 'ad_spend'), gm = num(a, 'gross_margin_pct'), c = cur(a);
  if (r === null || s === null || gm === null || s <= 0 || gm <= 0 || gm > 100 || r < 0) return toolError('Spend must be above 0 and margin between 0 and 100.');
  const roas = r / s, be = 100 / gm, profit = r * gm / 100 - s;
  const verdict = roas >= be ? 'Above break-even: gross profit from these sales covers the ad spend.' : 'Below break-even: gross profit from these sales does not cover the ad spend.';
  return toolResult(`ROAS: ${fmt(roas, 2)}x\nBreak-even ROAS at ${trimNum(gm, 1)}% margin: ${fmt(be, 2)}x\nGross profit after ad spend: ${money(profit, c)}\n${verdict}`,
    { currency: c, roas: r2(roas), break_even_roas: r2(be), gross_profit_after_ad_spend: r2(profit), above_break_even: roas >= be });
}
function tBudget(a) {
  const t = num(a, 'target_customers'), cpc = num(a, 'cost_per_click'), cl = num(a, 'click_to_lead_pct'), lc = num(a, 'lead_to_customer_pct'), c = cur(a);
  if ([t, cpc, cl, lc].some((x) => x === null) || t < 1 || cpc <= 0 || cl <= 0 || cl > 100 || lc <= 0 || lc > 100) return toolError('All inputs must be above 0 and percentages at most 100.');
  const leads = t / (lc / 100), clicks = leads / (cl / 100), budget = clicks * cpc;
  const count = (v) => money(Math.ceil(v), c).replace('Rs ', '').replace(c + ' ', '').trim();
  return toolResult(`To win ${Math.trunc(t)} customers a month you need about ${count(leads)} leads from ${count(clicks)} clicks.\nEstimated monthly ad budget: ${money(budget, c)}\nImplied cost per lead: ${money(budget / leads, c)}, cost per customer: ${money(budget / t, c)}\nThis is a planning estimate; real CPCs and conversion rates move with competition and season.`,
    { currency: c, leads_needed: Math.ceil(leads), clicks_needed: Math.ceil(clicks), monthly_budget: r2(budget), cost_per_lead: r2(budget / leads), cost_per_customer: r2(budget / t) });
}
// Keyword synonyms so "acquisitions" also finds "agreed to buy" and "merged". Whole-word regexes avoid "buyers".
const SYNONYMS = [
  [/\b(acqui\w*|m&a|merg\w*|buy\w*|bought|takeover)/, /\b(acqui\w*|merg\w*|buy|bought|takeover)\b/],
  [/\b(expan\w*|international|global|overseas|abroad|foreign|new markets?|cross-border)/, /\b(first (foreign|international) market|foreign|overseas|uae|saudi|middle east|the us|us market|into the us|australia\w*|singapore\w*|london|across \d+ countries|cross-border)\b/],
  [/\b(ai|agents?|agentic)\b/, /\b(ai|agents?|agentic|gen-ai|foundation model)\b/],
];
const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function keywordMatcher(kw) {
  if (!kw) return null;
  for (const [trigger, rx] of SYNONYMS) if (trigger.test(kw)) return (h) => h.includes(kw) || rx.test(h);
  return (h) => h.includes(kw);
}
function tMoves(a) {
  const sector = typeof a.sector === 'string' ? a.sector.toLowerCase() : 'any';
  const company = typeof a.company === 'string' ? a.company.trim().toLowerCase() : '';
  const kw = typeof a.keyword === 'string' ? a.keyword.trim().toLowerCase() : '';
  const lim = num(a, 'limit'); const limit = lim === null ? 5 : Math.max(1, Math.min(14, Math.trunc(lim)));
  const match = keywordMatcher(kw);
  let out = [];
  for (const [sec, ed] of Object.entries(DATA.editions)) {
    if (sector !== 'any' && sector !== sec) continue;
    for (const m of ed.moves) {
      if (company && !m.company.toLowerCase().includes(company)) continue;
      const hay = (m.move + ' ' + m.company).toLowerCase();
      if (match && !match(hay)) continue;
      out.push({ ...m, sector: sec, edition_url: ed.edition_url });
    }
  }
  const total = out.length; out = out.slice(0, limit);
  if (!total) return toolResult(`No matching moves in Growth Moves 2026 (fintech, ecommerce, healthtech, saas). Browse all editions: ${DATA.hub_url}`, { matches: 0, moves: [], hub_url: DATA.hub_url });
  const lines = out.map((m) => `${m.company} (${m.leader}, ${m.date}): ${m.move} Source: ${m.source_url}`);
  return toolResult(`${out.length} of ${total} matching moves from upGrowth Growth Moves 2026:\n${lines.join('\n')}\nFull research: ${DATA.hub_url}`, { matches: total, moves: out, hub_url: DATA.hub_url });
}
// ---------- v1.2 tools: max_affordable_cac, period_change, seo_roi, ai_crawler_access_check ----------
function tMaxCac(a) {
  const arpu = num(a, 'monthly_revenue_per_customer'), gm = num(a, 'gross_margin_pct'), churn = num(a, 'monthly_churn_pct'), c = cur(a);
  const ratio = num(a, 'target_ltv_to_cac') === null ? 3 : num(a, 'target_ltv_to_cac');
  const l2c = num(a, 'lead_to_customer_pct');
  if ([arpu, gm, churn].some((x) => x === null)) return toolError('Missing a required number.');
  if (arpu <= 0 || gm <= 0 || gm > 100 || churn <= 0 || churn > 100 || ratio <= 0 || (l2c !== null && (l2c <= 0 || l2c > 100))) return toolError('Revenue, margin and churn must be above 0; percentages at most 100; target ratio above 0.');
  const gp = arpu * gm / 100, life = 100 / churn, ltv = gp * life, maxCac = ltv / ratio, payback = maxCac / gp;
  let text = `LTV (gross margin basis): ${money(ltv, c)} over about ${life.toFixed(1)} months\nMaximum affordable CAC at ${trimNum(ratio, 1)}:1 LTV:CAC: ${money(maxCac, c)}\nCAC payback at that CAC: ${fmt(payback, 1)} months`;
  const out = { currency: c, ltv: r2(ltv), target_ltv_to_cac: ratio, max_cac: r2(maxCac), payback_months_at_max_cac: r1(payback) };
  if (l2c !== null) { const cpl = maxCac * l2c / 100; text += `\nMaximum affordable cost per lead at ${trimNum(l2c, 1)}% lead to customer: ${money(cpl, c)}`; out.max_cpl = r2(cpl); }
  text += '\nAbove these numbers, each new customer earns back less than the target ratio. Ratios vary by business model and stage.';
  return toolResult(text, out);
}
function tChange(a) {
  const prev = num(a, 'previous_value'), now = num(a, 'current_value');
  const label = ['yoy', 'mom', 'qoq', 'wow', 'custom'].includes(a.comparison) ? a.comparison : 'custom';
  if (prev === null || now === null) return toolError('Missing a required number.');
  if (prev === 0) return toolError('Previous value is 0, so the % change is undefined. Report the absolute change instead.');
  const diff = now - prev, pct = diff / Math.abs(prev) * 100;
  const name = { yoy: 'Year over year (YoY)', mom: 'Month over month (MoM)', qoq: 'Quarter over quarter (QoQ)', wow: 'Week over week (WoW)', custom: 'Change' }[label];
  return toolResult(`${name} change: ${pct >= 0 ? '+' : ''}${fmt(pct, 2)}%\nAbsolute change: ${diff >= 0 ? '+' : ''}${trimNum(diff, 2)} (from ${trimNum(prev, 2)} to ${trimNum(now, 2)})\nFormula: (current - previous) / previous x 100`,
    { comparison: label, previous_value: prev, current_value: now, absolute_change: r2(diff), pct_change: r2(pct) });
}
function tSeoRoi(a) {
  const visits = num(a, 'monthly_organic_visits_gain'), cr = num(a, 'conversion_rate_pct'), val = num(a, 'value_per_conversion'), cost = num(a, 'monthly_seo_cost'), c = cur(a);
  const gm = num(a, 'gross_margin_pct') === null ? 100 : num(a, 'gross_margin_pct');
  const months = num(a, 'months') === null ? 12 : num(a, 'months');
  if ([visits, cr, val, cost].some((x) => x === null)) return toolError('Missing a required number.');
  if (visits < 0 || cr <= 0 || cr > 100 || val < 0 || cost <= 0 || gm <= 0 || gm > 100 || months <= 0) return toolError('Cost and conversion rate must be above 0; percentages at most 100.');
  const conv = visits * cr / 100, rev = conv * val, gp = rev * gm / 100, roi = (gp - cost) / cost * 100;
  const totalCost = cost * months, totalGp = gp * months;
  const beVisits = cost / ((cr / 100) * val * gm / 100);
  return toolResult(`Extra conversions a month: ${fmt(conv, 1)}\nExtra revenue a month: ${money(rev, c)}${gm < 100 ? ` (gross profit ${money(gp, c)} at ${trimNum(gm, 1)}% margin)` : ''}\nMonthly SEO ROI: ${fmt(roi, 1)}% on ${money(cost, c)} a month\nOver ${trimNum(months, 1)} months: ${money(totalGp, c)} ${gm < 100 ? 'gross profit' : 'revenue'} against ${money(totalCost, c)} cost\nBreak-even: about ${Math.ceil(beVisits).toLocaleString('en-US')} extra organic visits a month\nThis assumes the traffic gain is already reached; SEO gains usually build over several months.`,
    { currency: c, conversions_per_month: r2(conv), revenue_per_month: r2(rev), gross_profit_per_month: r2(gp), monthly_roi_pct: r2(roi), months, total_cost: r2(totalCost), total_return: r2(totalGp), break_even_visits_per_month: Math.ceil(beVisits) });
}
const AI_BOTS = [
  ['GPTBot', 'OpenAI', 'content that may be used to train OpenAI models'],
  ['OAI-SearchBot', 'OpenAI', 'showing sites in ChatGPT search results'],
  ['ChatGPT-User', 'OpenAI', 'pages fetched when a ChatGPT user asks a question'],
  ['ClaudeBot', 'Anthropic', 'public web content for training Anthropic models'],
  ['Claude-SearchBot', 'Anthropic', 'improving the relevance of Claude search results'],
  ['Claude-User', 'Anthropic', 'pages fetched when a Claude user asks a question'],
  ['PerplexityBot', 'Perplexity', 'showing and linking sites in Perplexity search results'],
  ['Google-Extended', 'Google', 'use of content for Gemini training and grounding (not Google Search)'],
  ['Googlebot', 'Google', 'Google Search crawling'],
];
function parseRobots(txt) {
  const groups = []; let cur = null, lastWasUA = false;
  for (let line of txt.split(/\r?\n/)) {
    line = line.replace(/#.*$/, '').trim(); if (!line) continue;
    const m = line.match(/^([A-Za-z-]+)\s*:\s*(.*)$/); if (!m) continue;
    const k = m[1].toLowerCase(), v = m[2].trim();
    if (k === 'user-agent') { if (!cur || !lastWasUA) { cur = { agents: [], rules: [] }; groups.push(cur); } cur.agents.push(v.toLowerCase()); lastWasUA = true; }
    else { lastWasUA = false; if (cur && (k === 'allow' || k === 'disallow')) cur.rules.push([k, v]); }
  }
  return groups;
}
function botStatus(groups, bot) {
  const b = bot.toLowerCase();
  let g = groups.filter((x) => x.agents.some((u) => u !== '*' && b.includes(u)));
  let via = bot;
  if (!g.length) { g = groups.filter((x) => x.agents.includes('*')); via = '*'; }
  if (!g.length) return { status: 'allowed', via: 'no rule' };
  const rules = g.flatMap((x) => x.rules);
  const dis = rules.filter(([k, v]) => k === 'disallow' && v !== '');
  const rootBlocked = dis.some(([, v]) => v === '/' || v === '/*');
  const rootAllowed = rules.some(([k, v]) => k === 'allow' && (v === '/' || v === '/*' || v === '/$'));
  if (rootBlocked && !rootAllowed) return { status: 'blocked', via };
  if (dis.length) return { status: 'allowed', via, excluded_paths: dis.slice(0, 5).map(([, v]) => v), excluded_count: dis.length };
  return { status: 'allowed', via };
}
async function getText(url) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 6000);
  try {
    const r = await fetch(url, { redirect: 'follow', signal: ctl.signal, headers: { 'User-Agent': 'upGrowth-Growth-Toolkit/1.4 (+https://upgrowth.in/growth-toolkit-mcp/)' } });
    const body = r.ok ? (await r.text()).slice(0, 200000) : '';
    return { status: r.status, body, type: r.headers.get('content-type') || '' };
  } catch (e) { return { status: 0, body: '', type: '' }; } finally { clearTimeout(t); }
}
async function tCrawler(a) {
  let host = typeof a.domain === 'string' ? a.domain.trim().toLowerCase() : '';
  host = host.replace(/^https?:\/\//, '').replace(/[\/?#].*$/, '').replace(/^www\.(?=.+\..+)/, 'www.');
  if (!/^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(host)) return toolError('Give a public domain name such as example.com (no IP addresses, ports or paths).');
  const robots = await getText(`https://${host}/robots.txt`);
  const llms = await getText(`https://${host}/llms.txt`);
  if (robots.status === 0) return toolError(`Could not reach https://${host}/robots.txt. Check the domain is live over HTTPS.`);
  if (![200, 404, 410].includes(robots.status)) return toolError(`robots.txt on ${host} answered HTTP ${robots.status} to our checker. That usually means a firewall or bot rule blocked the request, so the crawler rules can't be read and this check won't guess. Open https://${host}/robots.txt in a browser to see them.`);
  const hasRobots = robots.status === 200 && robots.body.trim().length > 0;
  const groups = hasRobots ? parseRobots(robots.body) : [];
  const bots = AI_BOTS.map(([name, owner, purpose]) => ({ bot: name, owner, purpose, ...botStatus(groups, name) }));
  const hasLlms = llms.status === 200 && llms.body.trim().length > 0 && !/text\/html/i.test(llms.type);
  const blocked = bots.filter((b) => b.status === 'blocked').map((b) => b.bot);
  const lines = bots.map((b) => `${b.bot} (${b.owner}): ${b.status.toUpperCase()}${b.excluded_count ? ` (excludes ${b.excluded_count} path${b.excluded_count > 1 ? 's' : ''}, e.g. ${b.excluded_paths.slice(0, 3).join(', ')})` : ''}. Controls ${b.purpose}.`);
  const text = `AI crawler access for ${host} (robots.txt ${hasRobots ? 'found' : robots.status === 200 ? 'empty, so all bots are allowed' : 'not found, so all bots are allowed'}):\n${lines.join('\n')}\nllms.txt: ${hasLlms ? 'present' : 'not found'}\n${blocked.length ? `Blocked: ${blocked.join(', ')}. Our reading: assistants that rely on a blocked bot can't read fresh pages from this site, which limits how they can cite it.` : 'No AI bot is fully blocked.'}\nNote: Perplexity-User and other user-triggered fetchers may not follow robots.txt. This check reads robots.txt only, not firewall or CDN bot rules.`;
  return toolResult(text, { domain: host, robots_txt_found: hasRobots, robots_status: robots.status, llms_txt_found: hasLlms, bots, blocked });
}
// ---------- v1.3 tools: mdr_charges, robots_txt_generator ----------
function tMdr(a) {
  const v = num(a, 'sales_value'), mdr = num(a, 'mdr_pct'), n = num(a, 'transactions'), fee = num(a, 'fixed_fee_per_transaction'), c = cur(a);
  const gst = num(a, 'gst_pct') === null ? 18 : num(a, 'gst_pct');
  if (v === null || mdr === null) return toolError('Missing a required number.');
  if (v <= 0 || mdr < 0 || mdr > 100 || gst < 0 || gst > 100 || (n !== null && n < 1) || (fee !== null && fee < 0)) return toolError('Sales value must be above 0; percentages between 0 and 100.');
  if (fee !== null && fee > 0 && n === null) return toolError('A fixed fee per transaction needs the number of transactions.');
  const pctFee = v * mdr / 100, fixed = fee && n ? fee * n : 0, mdrFee = pctFee + fixed, tax = mdrFee * gst / 100, total = mdrFee + tax, eff = total / v * 100, net = v - total;
  const text = `MDR fee: ${money(mdrFee, c)} (${trimNum(mdr, 2)}% of ${money(v, c)}${fixed ? ` plus ${money(fixed, c)} in fixed fees` : ''})\nGST at ${trimNum(gst, 1)}% on the fee: ${money(tax, c)}\nTotal cost: ${money(total, c)}, an effective rate of ${fmt(eff, 2)}%\nNet settlement: ${money(net, c)}\nGST-registered businesses can usually claim GST on MDR as input tax credit. UPI, RuPay and card rates differ, so use your provider's current rate card.`;
  return toolResult(text, { currency: c, sales_value: v, mdr_fee: r2(mdrFee), gst: r2(tax), total_cost: r2(total), effective_rate_pct: r2(eff), net_settlement: r2(net) });
}
const BOT_GROUPS = {
  ai_training: { label: 'AI model training', bots: ['GPTBot', 'ClaudeBot', 'Google-Extended'] },
  ai_search: { label: 'AI search results', bots: ['OAI-SearchBot', 'Claude-SearchBot', 'PerplexityBot'] },
  ai_user_fetch: { label: 'user-triggered fetches', bots: ['ChatGPT-User', 'Claude-User', 'Perplexity-User'] },
};
function tRobots(a) {
  const choice = (k) => (a[k] === 'block' ? 'block' : 'allow');
  const raw = Array.isArray(a.disallow_paths) ? a.disallow_paths : [];
  if (raw.length > 20) return toolError('Give at most 20 paths.');
  const paths = [];
  for (const p of raw) {
    if (typeof p !== 'string' || !/^\/[^\s#]{0,200}$/.test(p.trim())) return toolError('Each path must start with / and contain no spaces, for example /wp-admin/.');
    if (!paths.includes(p.trim())) paths.push(p.trim());
  }
  let sitemap = '';
  if (a.sitemap_url !== undefined && a.sitemap_url !== null && a.sitemap_url !== '') {
    if (typeof a.sitemap_url !== 'string' || !/^https?:\/\/[^\s]{3,300}$/.test(a.sitemap_url.trim())) return toolError('The sitemap must be a full URL such as https://example.com/sitemap.xml.');
    sitemap = a.sitemap_url.trim();
  }
  const lines = ['# robots.txt generated by the upGrowth Growth Toolkit (https://upgrowth.in/growth-toolkit-mcp/)', '', 'User-agent: *'];
  if (paths.length) paths.forEach((p) => lines.push('Disallow: ' + p)); else lines.push('Allow: /');
  const blocked = [], summary = {};
  for (const k of Object.keys(BOT_GROUPS)) {
    summary[k] = choice(k);
    if (choice(k) === 'block') {
      blocked.push(...BOT_GROUPS[k].bots);
      lines.push('', `# Block ${BOT_GROUPS[k].label}`);
      BOT_GROUPS[k].bots.forEach((b) => lines.push('User-agent: ' + b));
      lines.push('Disallow: /');
    }
  }
  if (sitemap) lines.push('', 'Sitemap: ' + sitemap);
  const file = lines.join('\n') + '\n';
  const notes = ['Upload this as robots.txt at the root of your domain. It never blocks Googlebot or Google Search.'];
  if (summary.ai_training === 'block') notes.push('Google-Extended controls use of your content for Gemini training and grounding; it does not affect Google Search.');
  if (summary.ai_search === 'block') notes.push("Our reading: blocking AI search crawlers keeps your pages out of ChatGPT search, Claude search and Perplexity results, so those assistants can't cite you.");
  if (summary.ai_user_fetch === 'block') notes.push('Perplexity-User and some other user-triggered fetchers may not follow robots.txt.');
  notes.push('robots.txt is a request, not access control. Check the result with ai_crawler_access_check once it is live.');
  return toolResult('```\n' + file + '```\n' + notes.join('\n'), { robots_txt: file, choices: summary, blocked_bots: blocked, disallow_paths: paths, sitemap_url: sitemap || null });
}
// ---------- v1.4 tools ----------
const pct = (v, d = 2) => fmt(v, d) + '%';
const str = (v, max = 2000) => (typeof v === 'string' ? v.trim().slice(0, max) : '');
const isUrl = (v) => typeof v === 'string' && /^https?:\/\/[^\s<>"]{3,500}$/.test(v.trim());
const isDate = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}([T ][0-9:.+\-Z]*)?$/.test(v.trim());
const ld = (obj) => '<script type="application/ld+json">\n' + JSON.stringify(obj, null, 2).replace(/</g, '\\u003c') + '\n</script>';
function tSchema(a) {
  const t = a.schema_type, d = a.data && typeof a.data === 'object' ? a.data : {};
  const warn = [], notes = [];
  const urls = (arr) => (Array.isArray(arr) ? arr.filter(isUrl).map((u) => u.trim()).slice(0, 10) : []);
  const addr = (x) => (x && typeof x === 'object' ? Object.fromEntries(Object.entries({ '@type': 'PostalAddress', streetAddress: str(x.street), addressLocality: str(x.locality), addressRegion: str(x.region), postalCode: str(x.postal_code), addressCountry: str(x.country) }).filter(([, v]) => v)) : null);
  let o;
  if (t === 'faq') {
    const qs = (Array.isArray(d.questions) ? d.questions : []).filter((q) => q && str(q.question) && str(q.answer)).slice(0, 30);
    if (!qs.length) return toolError('Give data.questions as a list of {question, answer}.');
    o = { '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: qs.map((q) => ({ '@type': 'Question', name: str(q.question, 500), acceptedAnswer: { '@type': 'Answer', text: str(q.answer, 3000) } })) };
    notes.push('Google stopped showing FAQ rich results in Search on 7 May 2026, so this markup will not produce an FAQ snippet. Our reading: it still describes your questions and answers in a structured way for other systems that read the page.');
  } else if (t === 'local_business') {
    if (!str(d.name) || !addr(d.address)) return toolError('Local business needs data.name and data.address (Google lists both as required).');
    const type = /^[A-Za-z]{3,40}$/.test(str(d.business_type)) ? str(d.business_type) : 'LocalBusiness';
    o = { '@context': 'https://schema.org', '@type': type, name: str(d.name), address: addr(d.address) };
    if (isUrl(d.url)) o.url = d.url.trim(); else warn.push('url');
    if (str(d.telephone)) o.telephone = str(d.telephone, 40); else warn.push('telephone');
    if (isUrl(d.image)) o.image = d.image.trim();
    if (str(d.price_range)) o.priceRange = str(d.price_range, 40);
    if (d.geo && num(d.geo, 'latitude') !== null && num(d.geo, 'longitude') !== null) o.geo = { '@type': 'GeoCoordinates', latitude: num(d.geo, 'latitude'), longitude: num(d.geo, 'longitude') }; else warn.push('geo');
    const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const oh = (Array.isArray(d.opening_hours) ? d.opening_hours : []).map((h) => ({ '@type': 'OpeningHoursSpecification', dayOfWeek: (Array.isArray(h.days) ? h.days : [h.days]).filter((x) => DAYS.includes(x)), opens: /^\d{2}:\d{2}$/.test(h.opens) ? h.opens : '', closes: /^\d{2}:\d{2}$/.test(h.closes) ? h.closes : '' })).filter((h) => h.dayOfWeek.length && h.opens && h.closes);
    if (oh.length) o.openingHoursSpecification = oh; else warn.push('opening_hours');
  } else if (t === 'organization') {
    if (!str(d.name)) return toolError('Give data.name.');
    const type = /^[A-Za-z]{3,40}$/.test(str(d.organization_type)) ? str(d.organization_type) : 'Organization';
    o = { '@context': 'https://schema.org', '@type': type, name: str(d.name) };
    if (str(d.legal_name)) o.legalName = str(d.legal_name);
    if (isUrl(d.url)) o.url = d.url.trim(); else warn.push('url');
    if (isUrl(d.logo)) o.logo = d.logo.trim(); else warn.push('logo');
    if (str(d.description)) o.description = str(d.description);
    if (isDate(d.founding_date) || /^\d{4}$/.test(str(d.founding_date))) o.foundingDate = str(d.founding_date);
    if (str(d.email)) o.email = str(d.email, 120);
    if (str(d.telephone)) o.telephone = str(d.telephone, 40);
    if (addr(d.address)) o.address = addr(d.address); else warn.push('address');
    if (urls(d.same_as).length) o.sameAs = urls(d.same_as); else warn.push('same_as');
  } else if (t === 'article') {
    if (!str(d.headline)) return toolError('Give data.headline.');
    const type = ['Article', 'BlogPosting', 'NewsArticle'].includes(d.article_type) ? d.article_type : 'Article';
    o = { '@context': 'https://schema.org', '@type': type, headline: str(d.headline, 300) };
    if (isUrl(d.url)) o.mainEntityOfPage = { '@type': 'WebPage', '@id': d.url.trim() };
    if (urls(d.images).length) o.image = urls(d.images); else warn.push('images');
    if (isDate(d.date_published)) o.datePublished = d.date_published.trim(); else warn.push('date_published');
    if (isDate(d.date_modified)) o.dateModified = d.date_modified.trim();
    const au = (Array.isArray(d.authors) ? d.authors : []).filter((x) => x && str(x.name)).slice(0, 10).map((x) => Object.fromEntries(Object.entries({ '@type': 'Person', name: str(x.name, 120), jobTitle: str(x.job_title, 120), url: isUrl(x.url) ? x.url.trim() : '' }).filter(([, v]) => v)));
    if (au.length) o.author = au; else warn.push('authors');
    if (d.publisher && str(d.publisher.name)) { o.publisher = { '@type': 'Organization', name: str(d.publisher.name) }; if (isUrl(d.publisher.logo)) o.publisher.logo = { '@type': 'ImageObject', url: d.publisher.logo.trim() }; }
    if (str(d.headline).length > 110) notes.push('Long headlines may be cut off on some devices, per Google\'s Article guidance.');
  } else if (t === 'product') {
    if (!str(d.name)) return toolError('Give data.name.');
    const price = num(d, 'price'), rv = num(d, 'rating_value'), rc = num(d, 'review_count');
    if (price === null && (rv === null || rc === null)) return toolError('Product needs a price or a rating (rating_value and review_count): Google requires offers, review or aggregateRating.');
    o = { '@context': 'https://schema.org', '@type': 'Product', name: str(d.name, 300) };
    if (str(d.description)) o.description = str(d.description);
    if (urls(d.images).length) o.image = urls(d.images); else warn.push('images');
    if (str(d.brand)) o.brand = { '@type': 'Brand', name: str(d.brand, 120) };
    if (str(d.sku)) o.sku = str(d.sku, 80);
    if (price !== null) {
      o.offers = { '@type': 'Offer', price: price, priceCurrency: cur(d) };
      const av = ['InStock', 'OutOfStock', 'PreOrder', 'SoldOut', 'BackOrder', 'LimitedAvailability', 'OnlineOnly', 'InStoreOnly', 'Discontinued'];
      if (av.includes(d.availability)) o.offers.availability = 'https://schema.org/' + d.availability; else warn.push('availability');
      if (isDate(d.price_valid_until)) o.offers.priceValidUntil = d.price_valid_until.trim();
      if (rv === null) notes.push('Google\'s Rich Results Test may warn about offers without review or aggregateRating.');
    }
    if (rv !== null && rc !== null && rc > 0) o.aggregateRating = { '@type': 'AggregateRating', ratingValue: rv, reviewCount: Math.round(rc) };
    notes.push('Only mark up ratings that real customers left on this page.');
  } else if (t === 'person') {
    if (!str(d.name)) return toolError('Give data.name.');
    o = { '@context': 'https://schema.org', '@type': 'Person', name: str(d.name, 120) };
    if (isUrl(d.url)) o.url = d.url.trim(); else warn.push('url');
    if (str(d.job_title)) o.jobTitle = str(d.job_title, 120);
    if (str(d.works_for)) o.worksFor = { '@type': 'Organization', name: str(d.works_for, 120) };
    if (isUrl(d.image)) o.image = d.image.trim();
    if (str(d.description)) o.description = str(d.description);
    if (urls(d.same_as).length) o.sameAs = urls(d.same_as); else warn.push('same_as');
  } else if (t === 'breadcrumb') {
    const items = (Array.isArray(d.items) ? d.items : []).filter((x) => x && str(x.name) && isUrl(x.url)).slice(0, 20);
    if (items.length < 2) return toolError('Give data.items as at least 2 {name, url} entries, home page first.');
    o = { '@context': 'https://schema.org', '@type': 'BreadcrumbList', itemListElement: items.map((x, i) => ({ '@type': 'ListItem', position: i + 1, name: str(x.name, 120), item: x.url.trim() })) };
  } else return toolError('schema_type must be faq, local_business, organization, article, product, person or breadcrumb.');
  if (warn.length) notes.push('Recommended but missing: ' + warn.join(', ') + '.');
  notes.push('Paste the script tag into the page HTML, then check it with Google\'s Rich Results Test or validator.schema.org. Markup must match what is visible on the page.');
  return toolResult('```html\n' + ld(o) + '\n```\n' + notes.join('\n'), { schema_type: t, json_ld: o, missing_recommended: warn });
}
function syl(w) { w = w.toLowerCase().replace(/[^a-z]/g, ''); if (!w) return 0; if (w.length <= 3) return 1; w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, '').replace(/^y/, ''); const m = w.match(/[aeiouy]{1,2}/g); return m ? m.length : 1; }
function tContent(a) {
  let raw = typeof a.text === 'string' ? a.text : '';
  if (!raw.trim()) return toolError('Give the text to check.');
  if (raw.length > 60000) return toolError('Text is over 60,000 characters. Check it in parts.');
  const headings = (raw.match(/<h[1-6][^>]*>|^#{1,6}\s/gim) || []).length;
  const h1 = (raw.match(/<h1[^>]*>|^#\s/gim) || []).length;
  const text = raw.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ').replace(/<\/(p|div|h[1-6]|li|br)>|<br\s*\/?>/gi, '\n\n').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/^#{1,6}\s+/gm, '').replace(/[*_`>]/g, ' ');
  const words = text.match(/[A-Za-z0-9À-ɏ'’-]+/g) || [];
  const wc = words.length; if (!wc) return toolError('No words found in the text.');
  const sentences = text.split(/[.!?]+(?:\s|$)/).map((s) => s.trim()).filter((s) => (s.match(/[A-Za-z0-9]+/g) || []).length > 0);
  const sc = Math.max(1, sentences.length);
  const paras = text.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => (p.match(/[A-Za-z0-9]+/g) || []).length > 0);
  const longS = sentences.filter((s) => (s.match(/[A-Za-z0-9'’-]+/g) || []).length > 25).length;
  const longP = paras.filter((p) => (p.match(/[A-Za-z0-9'’-]+/g) || []).length > 100).length;
  const sy = words.reduce((s, w) => s + syl(w), 0);
  const flesch = 206.835 - 1.015 * (wc / sc) - 84.6 * (sy / wc);
  const band = flesch >= 70 ? 'easy' : flesch >= 50 ? 'fairly difficult' : flesch >= 30 ? 'difficult' : 'very difficult';
  const lower = ' ' + words.join(' ').toLowerCase() + ' ';
  const first100 = ' ' + words.slice(0, 100).join(' ').toLowerCase() + ' ';
  const countKw = (k) => { const kk = (k.match(/[A-Za-z0-9À-ɏ'’-]+/g) || []).join(' ').toLowerCase(); if (!kk) return null; let n = 0, i = 0; const needle = ' ' + kk + ' '; while ((i = lower.indexOf(needle, i)) !== -1) { n++; i += needle.length - 1; } return { keyword: k.trim(), count: n, density_pct: r2(n * kk.split(' ').length / wc * 100), in_first_100_words: first100.includes(needle) }; };
  const lines = [`Words: ${fmt(wc, 0)} | Sentences: ${fmt(sc, 0)} | Paragraphs: ${fmt(paras.length, 0)} | Headings found: ${headings}${h1 > 1 ? ` (${h1} H1s; most pages use 1)` : ''}`,
    `Reading time: about ${Math.max(1, Math.round(wc / 200))} min at 200 words a minute`,
    `Average sentence length: ${fmt(wc / sc, 1)} words; sentences over 25 words: ${longS}; paragraphs over 100 words: ${longP}`,
    `Flesch reading ease (approximate, English): ${fmt(flesch, 0)}, ${band}`];
  const kws = [];
  if (typeof a.keyword === 'string' && a.keyword.trim()) { const k = countKw(a.keyword); if (k) { kws.push(k); lines.push(`Focus keyword "${k.keyword}": ${k.count} times, ${k.density_pct}% of words, ${k.in_first_100_words ? 'in' : 'NOT in'} the first 100 words`); } }
  for (const s of (Array.isArray(a.secondary_keywords) ? a.secondary_keywords.slice(0, 10) : [])) { if (typeof s !== 'string') continue; const k = countKw(s); if (k) { kws.push(k); lines.push(`"${k.keyword}": ${k.count} times, ${k.density_pct}%`); } }
  lines.push('There is no official ideal keyword density; Google\'s spam policies warn against keyword stuffing, so write for the reader first.');
  return toolResult(lines.join('\n'), { words: wc, sentences: sc, paragraphs: paras.length, headings, reading_time_minutes: Math.max(1, Math.round(wc / 200)), avg_sentence_words: r1(wc / sc), long_sentences: longS, long_paragraphs: longP, flesch_reading_ease: r1(flesch), keywords: kws });
}
const hEsc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function tMeta(a) {
  const title = str(a.title, 300), desc = str(a.description, 1000);
  if (!title || !desc) return toolError('Give a title and a description.');
  if (!isUrl(a.url)) return toolError('Give the full page URL, for example https://example.com/page/.');
  const url = a.url.trim(), img = isUrl(a.image_url) ? a.image_url.trim() : '', site = str(a.site_name, 100), tw = /^@?[A-Za-z0-9_]{1,15}$/.test(str(a.twitter_handle)) ? '@' + str(a.twitter_handle).replace(/^@/, '') : '';
  const type = a.page_type === 'article' ? 'article' : 'website';
  const tags = [`<title>${hEsc(title)}</title>`, `<meta name="description" content="${hEsc(desc)}">`, `<link rel="canonical" href="${hEsc(url)}">`,
    `<meta property="og:type" content="${type}">`, `<meta property="og:title" content="${hEsc(title)}">`, `<meta property="og:description" content="${hEsc(desc)}">`, `<meta property="og:url" content="${hEsc(url)}">`];
  if (site) tags.push(`<meta property="og:site_name" content="${hEsc(site)}">`);
  if (img) tags.push(`<meta property="og:image" content="${hEsc(img)}">`);
  tags.push(`<meta name="twitter:card" content="${img ? 'summary_large_image' : 'summary'}">`, `<meta name="twitter:title" content="${hEsc(title)}">`, `<meta name="twitter:description" content="${hEsc(desc)}">`);
  if (img) tags.push(`<meta name="twitter:image" content="${hEsc(img)}">`);
  if (tw) tags.push(`<meta name="twitter:site" content="${hEsc(tw)}">`);
  const notes = [`Title: ${title.length} characters${title.length > 60 ? ' (over 60, likely to be cut off in search results)' : ''}. Description: ${desc.length} characters${desc.length > 160 ? ' (over 160, likely to be cut off)' : desc.length < 70 ? ' (short; there may be room to say more)' : ''}.`,
    'The 60 and 160 character marks are our rule of thumb: Google truncates by pixel width, not a fixed count, and may rewrite snippets.'];
  if (!img) notes.push('No share image given, so links will show a small card without a picture.');
  return toolResult('```html\n' + tags.join('\n') + '\n```\n' + notes.join('\n'), { tags: tags.join('\n'), title_length: title.length, description_length: desc.length });
}
function tYoutube(a) {
  const v = num(a, 'monthly_views'), rpm = num(a, 'rpm'), cpm = num(a, 'cpm'), mp = num(a, 'monetized_playback_pct'), dur = num(a, 'avg_view_duration_minutes'), subs = num(a, 'subscribers'), c = cur(a);
  if (v === null || v <= 0) return toolError('Give monthly_views above 0.');
  let monthly, method;
  if (rpm !== null) { monthly = v * rpm / 1000; method = `${money(rpm, c)} RPM`; }
  else if (cpm !== null && mp !== null) { monthly = v * (mp / 100) * cpm / 1000 * 0.55; method = `${money(cpm, c)} CPM on ${trimNum(mp, 1)}% monetized playbacks, at the 55% long-form creator share`; }
  else return toolError('Give rpm (from YouTube Studio), or cpm with monetized_playback_pct.');
  const lines = [`Estimated earnings: ${money(monthly, c)} a month, ${money(monthly * 12, c)} a year (${fmt(v, 0)} views a month at ${method})`];
  const out = { currency: c, monthly_earnings: r2(monthly), yearly_earnings: r2(monthly * 12) };
  if (dur !== null && dur > 0) {
    const wh = v * dur / 60, yr = wh * 12; out.monthly_watch_hours = r1(wh); out.yearly_watch_hours = r1(yr);
    lines.push(`Watch hours: about ${fmt(wh, 0)} a month, ${fmt(yr, 0)} over 12 months at this pace (the YouTube Partner Program asks for 4,000 public long-form watch hours in 12 months${subs !== null ? ` and 1,000 subscribers; you have ${fmt(subs, 0)}` : ' plus 1,000 subscribers'})`);
    out.meets_watch_hours = yr >= 4000; if (subs !== null) out.meets_subscribers = subs >= 1000;
  }
  lines.push('RPM varies by audience country, niche and season. Use the RPM from your own YouTube Studio for a real estimate. Shorts earn from a separate pool at a 45% creator share and are not included here.');
  return toolResult(lines.join('\n'), out);
}
function tInsta(a) {
  const f = num(a, 'followers'), ppm = num(a, 'posts_per_month'), rpp = num(a, 'rate_per_post'), r1k = num(a, 'rate_per_1000_followers'), spm = num(a, 'stories_per_month'), rps = num(a, 'rate_per_story'), eng = num(a, 'avg_engagements_per_post'), c = cur(a);
  if (f === null || f < 1 || ppm === null || ppm < 0) return toolError('Give followers and posts_per_month.');
  const fee = rpp !== null ? rpp : r1k !== null ? f / 1000 * r1k : null;
  if (fee === null) return toolError('Give rate_per_post or rate_per_1000_followers. This tool models your own rates; it does not guess market rates.');
  const posts = fee * ppm, stories = spm !== null && rps !== null ? spm * rps : 0, monthly = posts + stories;
  const lines = [`Fee per post: ${money(fee, c)}${rpp === null ? ` (${money(r1k, c)} per 1,000 of ${fmt(f, 0)} followers)` : ''}`, `Monthly income: ${money(monthly, c)} (posts ${money(posts, c)}${stories ? `, stories ${money(stories, c)}` : ''}), ${money(monthly * 12, c)} a year`];
  const out = { currency: c, fee_per_post: r2(fee), monthly_income: r2(monthly), yearly_income: r2(monthly * 12) };
  if (eng !== null && eng > 0) { lines.push(`Cost per engagement for a brand: ${money(fee / eng, c)}; engagement rate per post: ${pct(eng / f * 100)}`); out.cost_per_engagement = r2(fee / eng); out.engagement_rate_pct = r2(eng / f * 100); }
  lines.push('This models brand-deal income from the rates you enter. It does not estimate payouts from Meta programmes.');
  return toolResult(lines.join('\n'), out);
}
function tEngage(a) {
  const parts = ['likes', 'comments', 'shares', 'saves'].map((k) => num(a, k) || 0), base = num(a, 'base_value'), posts = num(a, 'posts') || 1;
  const bt = ['followers', 'reach', 'impressions', 'views'].includes(a.base_type) ? a.base_type : 'followers';
  if (base === null || base <= 0) return toolError('Give base_value above 0.');
  const tot = parts.reduce((s, x) => s + x, 0); if (!tot) return toolError('Give at least 1 of likes, comments, shares or saves.');
  const er = tot / base * 100, per = er / posts;
  return toolResult(`Engagement rate by ${bt}: ${pct(er)} across ${fmt(posts, 0)} post${posts > 1 ? 's' : ''}${posts > 1 ? `, ${pct(per)} per post` : ''}\nInteractions: ${fmt(tot, 0)} (likes ${fmt(parts[0], 0)}, comments ${fmt(parts[1], 0)}, shares ${fmt(parts[2], 0)}, saves ${fmt(parts[3], 0)})\nFormula: interactions / ${bt}${posts > 1 ? ' / posts' : ''} x 100. Rates by reach or views run higher than by followers, so compare like with like.`,
    { base_type: bt, interactions: tot, engagement_rate_pct: r2(er), per_post_pct: r2(per) });
}
function tAdRev(a) {
  const pv = num(a, 'monthly_pageviews'), rpm = num(a, 'page_rpm'), apg = num(a, 'ads_per_page'), cpm = num(a, 'cpm'), fill = num(a, 'fill_rate_pct') === null ? 100 : num(a, 'fill_rate_pct'), c = cur(a);
  if (pv === null || pv <= 0) return toolError('Give monthly_pageviews above 0.');
  let m, how;
  if (rpm !== null) { m = pv * rpm / 1000; how = `${money(rpm, c)} page RPM`; }
  else if (apg !== null && cpm !== null) { m = pv * apg * (fill / 100) * cpm / 1000; how = `${trimNum(apg, 1)} ads a page, ${trimNum(fill, 1)}% fill, ${money(cpm, c)} CPM`; }
  else return toolError('Give page_rpm, or ads_per_page with cpm.');
  return toolResult(`Estimated ad revenue: ${money(m, c)} a month, ${money(m * 12, c)} a year (${fmt(pv, 0)} pageviews at ${how})\nEffective page RPM: ${money(m / pv * 1000, c)}\nRPM varies with audience country, niche, season and ad layout. Use the page RPM from your own ad reports for a real estimate.`,
    { currency: c, monthly_revenue: r2(m), yearly_revenue: r2(m * 12), effective_page_rpm: r2(m / pv * 1000) });
}
function tYtd(a) {
  let ty, ly, n;
  const tm = Array.isArray(a.this_year_monthly) ? a.this_year_monthly.map(Number) : null, lm = Array.isArray(a.last_year_monthly) ? a.last_year_monthly.map(Number) : null;
  if (tm && tm.length) {
    if (tm.some((x) => !Number.isFinite(x)) || tm.length > 12) return toolError('this_year_monthly must be up to 12 numbers.');
    if (!lm || lm.length < tm.length || lm.some((x) => !Number.isFinite(x))) return toolError('last_year_monthly needs at least as many months as this_year_monthly.');
    n = tm.length; ty = tm.reduce((s, x) => s + x, 0); ly = lm.slice(0, n).reduce((s, x) => s + x, 0);
  } else { ty = num(a, 'this_ytd_total'); ly = num(a, 'last_ytd_total'); n = num(a, 'months_elapsed'); if (ty === null || ly === null) return toolError('Give monthly arrays, or this_ytd_total and last_ytd_total.'); }
  if (ly === 0) return toolError('Last year\'s YTD total is 0, so growth % is undefined.');
  const g = (ty - ly) / Math.abs(ly) * 100;
  const lines = [`YTD this year: ${trimNum(ty, 2)} vs ${trimNum(ly, 2)} for the same ${n ? n + ' months' : 'period'} last year`, `YTD growth: ${g >= 0 ? '+' : ''}${pct(g)} (${ty - ly >= 0 ? '+' : ''}${trimNum(ty - ly, 2)})`];
  const out = { this_ytd: r2(ty), last_ytd: r2(ly), ytd_growth_pct: r2(g) };
  if (n) { const rr = ty / n * 12; lines.push(`Simple full-year run rate: ${trimNum(rr, 0)} (YTD average x 12; ignores seasonality)`); out.run_rate = r2(rr); out.months = n; }
  return toolResult(lines.join('\n'), out);
}
function tPpc(a) {
  const b = num(a, 'monthly_budget'), cpc = num(a, 'cost_per_click'), cr = num(a, 'conversion_rate_pct'), val = num(a, 'value_per_conversion'), gm = num(a, 'gross_margin_pct'), c = cur(a);
  if ([b, cpc, cr].some((x) => x === null) || b <= 0 || cpc <= 0 || cr <= 0 || cr > 100) return toolError('Give budget, CPC and conversion rate above 0.');
  const clicks = b / cpc, conv = clicks * cr / 100, cpa = b / conv;
  const lines = [`Clicks: ${fmt(clicks, 0)} | Conversions: ${fmt(conv, 1)} | Cost per acquisition: ${money(cpa, c)}`];
  const out = { currency: c, clicks: Math.round(clicks), conversions: r1(conv), cpa: r2(cpa) };
  if (val !== null) {
    const rev = conv * val, roas = rev / b; lines.push(`Revenue: ${money(rev, c)} | ROAS: ${fmt(roas, 2)}x`); out.revenue = r2(rev); out.roas = r2(roas);
    if (gm !== null) { const gp = rev * gm / 100 - b, be = val * gm / 100; lines.push(`Gross profit after ad spend: ${money(gp, c)} | Break-even CPA: ${money(be, c)} (${cpa <= be ? 'this forecast is under it' : 'this forecast is over it, so each sale loses money'})`); out.profit_after_ads = r2(gp); out.break_even_cpa = r2(be); }
  }
  lines.push('A forecast, not a guarantee: CPC and conversion rate move with competition, quality and landing page.');
  return toolResult(lines.join('\n'), out);
}
function tClv(a) {
  const aov = num(a, 'average_order_value'), f = num(a, 'purchases_per_year'), y = num(a, 'customer_lifespan_years'), gm = num(a, 'gross_margin_pct'), dr = num(a, 'annual_discount_rate_pct'), cac = num(a, 'cac'), c = cur(a);
  if ([aov, f, y, gm].some((x) => x === null) || aov <= 0 || f <= 0 || y <= 0 || gm <= 0 || gm > 100) return toolError('Give AOV, purchases a year, lifespan and margin above 0.');
  const annual = aov * f, rev = annual * y, gp = rev * gm / 100;
  const lines = [`Revenue per customer per year: ${money(annual, c)}`, `Lifetime revenue: ${money(rev, c)} | Lifetime gross profit (CLV): ${money(gp, c)} over ${trimNum(y, 1)} years`];
  const out = { currency: c, annual_revenue: r2(annual), lifetime_revenue: r2(rev), clv_gross_profit: r2(gp) };
  let base = gp;
  if (dr !== null && dr > 0) { let pv = 0; const ag = annual * gm / 100; const full = Math.floor(y); for (let i = 1; i <= full; i++) pv += ag / Math.pow(1 + dr / 100, i); if (y > full) pv += ag * (y - full) / Math.pow(1 + dr / 100, full + 1); lines.push(`Discounted CLV at ${trimNum(dr, 1)}% a year: ${money(pv, c)}`); out.clv_discounted = r2(pv); base = pv; }
  if (cac !== null && cac > 0) { lines.push(`LTV:CAC: ${fmt(base / cac, 2)}:1 at ${money(cac, c)} CAC`); out.ltv_to_cac = r2(base / cac); }
  return toolResult(lines.join('\n'), out);
}
function tEcom(a) {
  const rev = num(a, 'revenue'), o = num(a, 'orders'), s = num(a, 'sessions'), cu = num(a, 'customers'), tgt = num(a, 'target_revenue'), c = cur(a);
  if (rev === null || o === null || o < 1 || rev < 0) return toolError('Give revenue and at least 1 order.');
  const aov = rev / o; const lines = [`Average order value: ${money(aov, c)}`]; const out = { currency: c, aov: r2(aov) };
  if (s !== null && s > 0) { const cr = o / s * 100, rpv = rev / s; lines.push(`Conversion rate: ${pct(cr)} | Revenue per visitor: ${money(rpv, c)}`); out.conversion_rate_pct = r2(cr); out.revenue_per_visitor = r2(rpv);
    if (tgt !== null) { const need = tgt / rpv; lines.push(`To reach ${money(tgt, c)}: about ${fmt(Math.ceil(need), 0)} sessions at today's conversion rate and AOV (${fmt(Math.ceil(need - s), 0)} more), or lift revenue per visitor to ${money(tgt / s, c)} on today's traffic`); out.sessions_needed = Math.ceil(need); } }
  else if (tgt !== null) lines.push('Add sessions to work out the traffic needed for the target.');
  if (cu !== null && cu > 0) { lines.push(`Orders per customer: ${fmt(o / cu, 2)}`); out.orders_per_customer = r2(o / cu); }
  return toolResult(lines.join('\n'), out);
}
function tProject(a) {
  const s = num(a, 'start_value'), g = num(a, 'growth_rate_pct'), n = num(a, 'periods'), t = num(a, 'target_value');
  const pt = ['month', 'quarter', 'year'].includes(a.period_type) ? a.period_type : 'month';
  if (s === null || g === null || n === null || s <= 0 || g <= -100 || n < 1 || n > 120) return toolError('Give start_value above 0, growth_rate_pct above -100 and 1 to 120 periods.');
  const r = g / 100, end = s * Math.pow(1 + r, Math.round(n));
  const lines = [`After ${Math.round(n)} ${pt}s at ${g >= 0 ? '+' : ''}${trimNum(g, 2)}% a ${pt}: ${trimNum(end, 2)} (from ${trimNum(s, 2)}, ${fmt((end / s - 1) * 100, 1)}% total)`];
  if (n <= 24) lines.push('By period: ' + Array.from({ length: Math.round(n) }, (_, i) => `${i + 1}: ${trimNum(s * Math.pow(1 + r, i + 1), 0)}`).join(', '));
  const out = { period_type: pt, end_value: r2(end), total_growth_pct: r2((end / s - 1) * 100) };
  if (r > 0) { const dt = Math.log(2) / Math.log(1 + r); lines.push(`Doubling time: ${fmt(dt, 1)} ${pt}s`); out.doubling_periods = r1(dt); }
  if (t !== null) { if ((t > s && r > 0) || (t < s && r < 0)) { const k = Math.log(t / s) / Math.log(1 + r); lines.push(`Reaches ${trimNum(t, 2)} after ${fmt(k, 1)} ${pt}s`); out.periods_to_target = r1(k); } else if (t !== s) lines.push(`At this rate the value never reaches ${trimNum(t, 2)}.`); }
  return toolResult(lines.join('\n'), out);
}
function tAcos(a) {
  const sp = num(a, 'ad_spend'), sa = num(a, 'ad_sales'), gm = num(a, 'gross_margin_pct'), ts = num(a, 'total_sales'), c = cur(a);
  if (sp === null || sa === null || sp <= 0 || sa <= 0) return toolError('Give ad_spend and ad_sales above 0.');
  const acos = sp / sa * 100; const lines = [`ACoS: ${pct(acos)} | ROAS: ${fmt(sa / sp, 2)}x`]; const out = { currency: c, acos_pct: r2(acos), roas: r2(sa / sp) };
  if (gm !== null) { const p = sa * gm / 100 - sp; lines.push(`Break-even ACoS: ${pct(gm)} (your margin before ads). ${acos <= gm ? 'You are under it' : 'You are over it, so ad-driven sales lose money'}; profit after ads: ${money(p, c)}`); out.break_even_acos_pct = gm; out.profit_after_ads = r2(p); }
  if (ts !== null) { if (ts < sa) return toolError('total_sales should include ad sales, so it cannot be lower.'); lines.push(`TACoS: ${pct(sp / ts * 100)} of total sales; ads drive ${pct(sa / ts * 100)} of sales`); out.tacos_pct = r2(sp / ts * 100); }
  return toolResult(lines.join('\n'), out);
}
function tSov(a) {
  const bn = str(a.brand_name, 80), bv = num(a, 'brand_value');
  if (!bn || bv === null || bv < 0) return toolError('Give brand_name and brand_value.');
  const comps = (Array.isArray(a.competitors) ? a.competitors : []).filter((x) => x && str(x.name) && Number.isFinite(Number(x.value)) && Number(x.value) >= 0).slice(0, 20).map((x) => ({ name: str(x.name, 80), value: Number(x.value) }));
  if (!comps.length) return toolError('Give at least 1 competitor with a name and value.');
  const all = [{ name: bn, value: bv, brand: true }, ...comps], tot = all.reduce((s, x) => s + x.value, 0);
  if (!tot) return toolError('All values are 0.');
  all.sort((x, y) => y.value - x.value);
  const rows = all.map((x, i) => ({ rank: i + 1, name: x.name, value: x.value, share_pct: r2(x.value / tot * 100), brand: !!x.brand }));
  const me = rows.find((x) => x.brand);
  const metric = str(a.metric, 80) || 'the metric';
  return toolResult(`${bn} share of voice on ${metric}: ${pct(me.share_pct)}, rank ${me.rank} of ${rows.length}\n` + rows.map((x) => `${x.rank}. ${x.name}: ${pct(x.share_pct)} (${trimNum(x.value, 2)})`).join('\n'), { metric, total: tot, brand_share_pct: me.share_pct, brand_rank: me.rank, rows });
}
function tBreakEven(a) {
  const fc = num(a, 'fixed_costs'), p = num(a, 'price_per_unit'), vc = num(a, 'variable_cost_per_unit'), tp = num(a, 'target_profit'), c = cur(a);
  if ([fc, p, vc].some((x) => x === null) || fc < 0 || p <= 0 || vc < 0) return toolError('Give fixed costs, price and variable cost.');
  const cm = p - vc; if (cm <= 0) return toolError('Price is at or below variable cost, so the business never breaks even. Raise price or cut unit cost.');
  const u = fc / cm; const lines = [`Contribution margin: ${money(cm, c)} a unit (${pct(cm / p * 100)})`, `Break-even: ${fmt(Math.ceil(u), 0)} units, ${money(Math.ceil(u) * p, c)} revenue`];
  const out = { currency: c, contribution_margin: r2(cm), contribution_margin_pct: r2(cm / p * 100), break_even_units: Math.ceil(u), break_even_revenue: r2(Math.ceil(u) * p) };
  if (tp !== null && tp > 0) { const ut = (fc + tp) / cm; lines.push(`For ${money(tp, c)} profit: ${fmt(Math.ceil(ut), 0)} units, ${money(Math.ceil(ut) * p, c)} revenue`); out.units_for_target = Math.ceil(ut); }
  return toolResult(lines.join('\n'), out);
}
function tCampRoi(a) {
  const cost = num(a, 'cost'), rev = num(a, 'attributed_revenue'), gm = num(a, 'gross_margin_pct'), c = cur(a), nm = str(a.campaign_name, 80);
  if (cost === null || rev === null || cost <= 0 || rev < 0) return toolError('Give cost above 0 and attributed_revenue.');
  const roi = (rev - cost) / cost * 100; const lines = [`${nm ? nm + ': ' : ''}ROI on revenue: ${roi >= 0 ? '+' : ''}${pct(roi, 1)} (${money(rev, c)} revenue on ${money(cost, c)} cost, ${fmt(rev / cost, 2)}x)`];
  const out = { currency: c, roi_on_revenue_pct: r1(roi), revenue_multiple: r2(rev / cost) };
  if (gm !== null) { const gp = rev * gm / 100, r = (gp - cost) / cost * 100; lines.push(`ROI on gross profit: ${r >= 0 ? '+' : ''}${pct(r, 1)} (gross profit ${money(gp, c)}, net ${money(gp - cost, c)})`); out.roi_on_profit_pct = r1(r); out.net_profit = r2(gp - cost); }
  lines.push('ROI is only as good as the attribution behind the revenue figure.');
  return toolResult(lines.join('\n'), out);
}
function tAttrition(a) {
  const s = num(a, 'separations'), h0 = num(a, 'headcount_start'), h1 = num(a, 'headcount_end'), m = num(a, 'period_months') || 1;
  if ([s, h0, h1].some((x) => x === null) || s < 0 || h0 < 0 || h1 < 0 || m <= 0 || m > 12) return toolError('Give separations, start and end headcount, and a period of up to 12 months.');
  const avg = (h0 + h1) / 2; if (avg <= 0) return toolError('Average headcount is 0.');
  const r = s / avg * 100, ann = r * 12 / m;
  return toolResult(`Attrition rate: ${pct(r)} over ${trimNum(m, 1)} month${m > 1 ? 's' : ''} (${trimNum(s, 0)} left, average headcount ${trimNum(avg, 1)})\nAnnualised (simple, x ${trimNum(12 / m, 2)}): ${pct(ann)}\nFormula: separations / average of start and end headcount x 100. The same maths works for customer churn.`,
    { attrition_pct: r2(r), annualised_pct: r2(ann), average_headcount: r1(avg), period_months: m });
}
function callTool(name, a) {
  switch (name) {
    case 'unit_economics': return tUnit(a);
    case 'growth_rate': return tGrowth(a);
    case 'roas_check': return tRoas(a);
    case 'ad_budget_planner': return tBudget(a);
    case 'find_growth_moves': return tMoves(a);
    case 'max_affordable_cac': return tMaxCac(a);
    case 'period_change': return tChange(a);
    case 'seo_roi': return tSeoRoi(a);
    case 'ai_crawler_access_check': return tCrawler(a);
    case 'mdr_charges': return tMdr(a);
    case 'robots_txt_generator': return tRobots(a);
    case 'schema_generator': return tSchema(a);
    case 'content_seo_check': return tContent(a);
    case 'meta_tags_builder': return tMeta(a);
    case 'youtube_earnings': return tYoutube(a);
    case 'instagram_earnings': return tInsta(a);
    case 'engagement_rate': return tEngage(a);
    case 'website_ad_revenue': return tAdRev(a);
    case 'ytd_growth': return tYtd(a);
    case 'ppc_forecast': return tPpc(a);
    case 'customer_lifetime_value': return tClv(a);
    case 'ecommerce_metrics': return tEcom(a);
    case 'growth_projection': return tProject(a);
    case 'acos_check': return tAcos(a);
    case 'share_of_voice': return tSov(a);
    case 'break_even': return tBreakEven(a);
    case 'campaign_roi': return tCampRoi(a);
    case 'attrition_rate': return tAttrition(a);
    case 'book_strategy_call': return toolResult('Book a free 30-minute growth strategy call with upGrowth: ' + BOOKING_URL, { booking_url: BOOKING_URL, duration_minutes: 30 });
    default: return toolError('Unknown tool: ' + name);
  }
}

// Anonymous usage counts (Workers Analytics Engine): event, tool name, host and a coarse client family only.
// No IP addresses, no tool inputs or outputs.
let USAGE = null;
function clientFamily(ua) {
  const s = (ua || '').toLowerCase();
  if (/openai|chatgpt/.test(s)) return 'chatgpt';
  if (/claude|anthropic/.test(s)) return 'claude';
  if (/gemini|google/.test(s)) return 'google';
  if (/cursor/.test(s)) return 'cursor';
  if (/glama/.test(s)) return 'glama';
  if (/node|python|go-http|curl|axios|undici/.test(s)) return 'script';
  return 'other';
}
function track(event, tool, host, ua) {
  try { if (USAGE) USAGE.writeDataPoint({ blobs: [event, tool || '', host || '', clientFamily(ua)], doubles: [1], indexes: [event] }); } catch (e) { /* never block a call on metrics */ }
}

async function handleMcp(request, opts = {}) {
  const hidden = opts.hideTools || [];
  const host = new URL(request.url).hostname;
  const ua = request.headers.get('user-agent') || '';
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { Allow: 'POST, OPTIONS' } });
  if (request.method !== 'POST') return json({ error: 'Use POST with a JSON-RPC 2.0 body.' }, 405, { Allow: 'POST' });
  const raw = await request.text();
  if (raw.length > 65536) return rpcErr(null, -32600, 'Request too large', 413);
  let req; try { req = JSON.parse(raw); } catch { return rpcErr(null, -32700, 'Parse error', 400); }
  if (Array.isArray(req)) return rpcErr(null, -32600, 'Batch requests are not supported', 400);
  if (!req || typeof req !== 'object') return rpcErr(null, -32700, 'Parse error', 400);
  const id = Object.prototype.hasOwnProperty.call(req, 'id') ? req.id : null;
  const method = typeof req.method === 'string' ? req.method : '';
  const params = req.params && typeof req.params === 'object' && !Array.isArray(req.params) ? req.params : {};
  if (id === null && method.startsWith('notifications/')) return new Response(null, { status: 202 });
  switch (method) {
    case 'initialize':
      track('initialize', '', host, ua);
      return rpcOk(id, { protocolVersion: typeof params.protocolVersion === 'string' ? params.protocolVersion : DEFAULT_PROTOCOL,
        capabilities: { tools: { listChanged: false } }, serverInfo: { name: SERVER_NAME, title: 'upGrowth Growth Toolkit', version: SERVER_VERSION }, instructions: hidden.length ? INSTRUCTIONS.replace(' book_strategy_call when the user asks to talk to upGrowth.', '') : INSTRUCTIONS });
    case 'ping': return rpcOk(id, {});
    case 'tools/list': return rpcOk(id, { tools: toolDefinitions().filter((t) => !hidden.includes(t.name)) });
    case 'tools/call': {
      const args = params.arguments && typeof params.arguments === 'object' && !Array.isArray(params.arguments) ? params.arguments : {};
      const toolName = typeof params.name === 'string' ? params.name : '';
      if (hidden.includes(toolName)) return rpcOk(id, toolError('Unknown tool: ' + toolName));
      track('tools/call', toolName, host, ua);
      return rpcOk(id, await callTool(toolName, args));
    }
    default: return rpcErr(id, -32601, 'Method not found: ' + method);
  }
}

export default {
  async fetch(request, env) {
    USAGE = (env && env.USAGE) || null;
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '');
    // Dedicated host for clients that read root OAuth metadata (upgrowth.in/.well-known belongs to the WordPress MCP connector).
    if (url.hostname === 'mcp.upgrowth.in' && path === '/mcp') return handleMcp(request, { hideTools: ['book_strategy_call'] });
    if (path === '/.well-known/google-connected-apps') {
      if (!VERIFICATION_TOKENS.length) return json({ error: 'not configured' }, 404);
      return json({ verification_tokens: VERIFICATION_TOKENS });
    }
    if (path === '/.well-known/openai-apps-challenge') {
      return new Response('F21ry94d4TCAcFNhgh3W545-tP8XUGUQHgCwQyD4P2U', { headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' } });
    }
    if (path === '/.well-known/mcp-registry-auth') {
      return new Response('v=MCPv1; k=ed25519; p=Ty501sGSxSLvVyAR0DIs1TZV3SbRQKm/8998WZDUh+0=', { headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'public, max-age=300' } });
    }
    if (path === '/connected-app/mcp') return handleMcp(request);
    if (url.hostname !== 'upgrowth.in') return json({ error: 'not found' }, 404);
    return fetch(request); // anything else on a matched route falls through to the origin
  },
};
