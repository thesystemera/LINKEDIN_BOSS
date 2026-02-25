"""
Structured CV data extracted from Simon's resume.
Used by Gemini to generate cover letters and answer form questions.
"""

CV_SUPPLEMENTARY = {
    "role_preferences": {
        "instruction": "These are PREFERENCES, not hard requirements. Evaluate each role on its merits.",
        "preferred_levels": ["Staff Engineer", "Principal Engineer", "Lead Engineer", "Engineering Manager", "Technical Architect", "Solutions Architect", "Head of Engineering"],
        "open_to": "Strong mid-level roles (Senior Engineer) at great companies with growth potential. Current market reality means being flexible on title while ensuring role scope matches experience.",
        "context": "10+ years experience as CTO/Founder with proven leadership, architecture, and delivery. Prefer roles that leverage this experience, but open to right opportunities regardless of title."
    },

    "salary_strategy": {
        "instruction": "Be intelligent about salary. NO hardcoded numbers - evaluate each role on its merits.",
        "rules": [
            "1. If the job listing states a salary range, answer within that range (upper half is reasonable)",
            "2. If asked for 'expected salary' with no range given, research what's fair for that specific role title + level + location",
            "3. Consider NZ vs AU market differences (AU typically 10-20% higher for equivalent roles)",
            "4. Consider company size and industry (startups vs enterprise, tech vs non-tech)",
            "5. Consider role level: Junior < Mid < Senior < Staff < Principal < Director",
            "6. Remote roles may have location-adjusted pay - consider where the company is based",
            "7. Don't undersell, but don't price yourself out either - aim for fair market rate",
            "8. When uncertain, slightly conservative is better than losing the opportunity"
        ],
        "format": "Always return a single whole number with no symbols (e.g. 150000, not $150k or 150,000)"
    },

    "target_locations": ["New Zealand", "Melbourne", "Remote (AU/NZ)"],

    "background_context": {
        "instruction": "This provides the FULL story beyond the formal CV. Use this to understand depth of experience and familiarity with technology that spans decades.",
        "origin_story": {
            "age_9": "Founded first company 'Zenith Graphics' - childhood entrepreneurship",
            "age_11": "Built and operated 'The Dungeon' BBS (Bulletin Board System) - early networking and systems administration",
            "teenager_90s": "Heavy 3D animation work as a teenager in the 1990s - early exposure to computer graphics, rendering, and visual systems",
            "coding_journey": "Started programming in early 1990s as a child - has been immersed in technology for 30+ years",
            "context": "Child prodigy background - this explains the DEPTH of technical intuition and systems thinking. Not just '10 years as a CTO' - this is someone who's been solving technical problems since childhood."
        },
        "technology_timeline": {
            "Windows": "Using since early 1990s (~30+ years personal/professional combined). Primary professional development environment for ~20 years.",
            "3D_Graphics": "Started with 3D animation as a teenager in 90s, led to photogrammetry/VR career, continues with GLSL/shader work today - ~25+ years of graphics experience across different eras",
            "Operating_Systems": "Ran BBS systems as a kid (early networking/sysadmin concepts), professional system architecture and deployment for 10+ years",
            "Computers_General": "35+ years total immersion in computing - from childhood BBS operator to CTO of 11-person studio to solo architect of 60+ microservice platforms",
            "note": "The formal CV shows '10+ years professional experience' but the actual depth goes back to childhood. This context helps explain intuitive understanding of systems, architecture, and technology that can't be captured in a resume timeline."
        }
    },

    "technology_experience_years": {
        "instruction": "PROFESSIONAL work experience only (not personal/hobby use). When asked 'How many years of work experience with X?', use these numbers.",
        "primary_languages": {
            "Python": "10 years (primary language since 2014, heavy use in PLAiR, MoneyPrinter, deepPBR pipelines)",
            "JavaScript/React": "5 years (PLAiR frontend 2024-2025, various web projects)",
            "GLSL": "4 years (realityvirtual.co shader work, PLAiR visualizations)"
        },
        "secondary_languages": {
            "C++": "2-3 years (Unreal Engine context 2014-2020, mostly via Blueprints with occasional C++)",
            "PHP": "3 years (early web projects, not recent focus)",
            "SQL": "6 years (PostgreSQL in PLAiR/MoneyPrinter, MySQL in various projects)"
        },
        "platforms_environments": {
            "Windows": "10 years (primary development environment throughout professional career)",
            "Linux": "8 years (server deployments, Docker/containerization, production environments)",
            "Operating_Systems_General": "10 years (professional system architecture, deployment, containerization work)"
        },
        "frameworks_platforms": {
            "FastAPI": "2 years (PLAiR + MoneyPrinter 2024-2025, heavy production use)",
            "React": "2 years (PLAiR frontend 2024-2025)",
            "Unreal Engine": "6 years (realityvirtual.co 2014-2020, primary platform for VR work)",
            "Unity": "4 years (realityvirtual.co 2014-2020, secondary platform alongside Unreal)",
            "OpenCV": "3 years (deepPBR/deepMirror computer vision pipelines, photogrammetry preprocessing)",
            "Docker": "3 years (containerization for PLAiR/MoneyPrinter deployments)",
            "PyTorch/TensorFlow": "4 years (custom model training for deepPBR, audio enhancement)",
            "Maya": "5 years (3D asset pipelines, photogrammetry cleanup, VFX workflows)",
            "Houdini": "3 years (procedural workflows, VFX, point cloud processing)",
            "Substance Painter/Designer": "4 years (PBR texturing, directly informed deepPBR AI development)"
        },
        "note": "If asked about a technology NOT listed here, estimate conservatively from project dates in CV, or answer 0-1 if only peripheral exposure."
    },

    "supplementary_skills": {
        "creative_production": ["Adobe Premiere", "After Effects", "Blender"],
        "additional_languages": ["PHP"],
        "databases": ["MySQL", "various SQL databases"],
        "automation": ["Playwright browser automation", "AI-driven workflow optimization", "Self-documenting systems"],
        "meta": "Practices what I preach - this application was likely optimized by AI I built",
        "context": "Extensive video production background and breadth across many technologies not formally listed on CV"
    },

    "supplementary_experience": {
        "music": {
            "accomplishment": "Released 3 albums",
            "timeframe": "~2010-2011 (15 years ago)",
            "relevance": "Demonstrates creative background, complements audio engineering and DSP expertise"
        },
        "breadth": "Prolific across many tools and technologies - dabbled in everything from video production to various programming languages and frameworks beyond formal CV",
        "origin_story": {
            "context": "Lost all personal belongings in 2014 house fire. Attempted to digitally recreate the family home from photographs so he and his daughter could 'go home' digitally. This loss directly sparked the discovery of photogrammetry and the entire realityvirtual.co journey. Philosophy: 'You don't really know what you've lost until it's gone' - drives passion for 'Backing up the planet' and cultural preservation at scale.",
            "relevance": "Demonstrates deep personal connection to preservation work - turned personal loss into global-scale cultural heritage mission, systems thinking applied to preventing loss before it happens"
        },
        "team_leadership_detail": {
            "context": "Managed diverse technical roles at realityvirtual.co including pipeline engineers, lead deep learning engineers/data scientists (16+ years experience, mathematics backgrounds), digital artists, CG engineers, creative staff, and production teams across multiple simultaneous international projects.",
            "relevance": "Demonstrates ability to lead cross-functional teams spanning pure engineering, ML/AI research, creative production, and business operations"
        },
        "distributed_systems_vision": {
            "context": "'Backup the Planet' philosophy extends beyond individual projects - designed vision for distributed global acquisition network with photographer royalties, automated processing pipelines, and democratized access to cultural preservation. Mass automation via AI to achieve 'exponential environmental encapsulation with minimal human input.'",
            "relevance": "Demonstrates systems-level thinking at global scale, sustainable ecosystem design, and automation-first architecture philosophy"
        },
        "meta_automation": {
            "context": "Built custom AI-powered job application system (Playwright + Gemini) that extracts form fields, generates contextual answers, and optimizes application throughput. Because why apply to jobs manually when you can architect a solution?",
            "relevance": "Demonstrates end-to-end automation thinking, AI orchestration, and the kind of 'scratch your own itch' engineering philosophy that drives innovation"
        },
        "pimax_shanghai_conference": {
            "context": "Virtual speaker at Pimax Shanghai VR Conference 2022. Presented on VR technology and photogrammetry workflows to Chinese VR industry audience. Recording available on YouTube.",
            "relevance": "Demonstrates international industry recognition, established relationships with Chinese VR hardware companies, and ability to present technical content to global audiences"
        }
    },

    "contact_details": {
        "first_name": "Simon",
        "last_name": "Che de Boer",
        "email": "simon@realityvirtual.co",
        "phone": "+64211490191",
        "phone_number": "+64211490191",
        "mobile_phone_number": "+64211490191",
        "phone_country_code": "New Zealand (+64)",
        "city": "Auckland",
        "location": "Auckland, New Zealand"
    },

    "residency_status": {
        "citizenship": "New Zealand Citizen",
        "australia_work_rights": "Yes - NZ citizens have automatic work rights in Australia under the Trans-Tasman Travel Arrangement (Special Category Visa subclass 444, granted on arrival)",
        "new_zealand_work_rights": "Yes - Citizen",
        "authorized_to_work_in_au_nz": "Yes",
        "require_sponsorship_au_nz": "No",
        "require_sponsorship_asia": "Yes - would need visa sponsorship for China/Singapore/Hong Kong, but qualifies for China Category A (high-end talent) fast-track due to Lumiere Award, TEDx speaker, Forbes recognition, and specialized VR/AI expertise",
        "current_location": "New Zealand",
        "notice_period": "Immediate (0 days/weeks - available to start right away)",
        "willing_to_relocate": "Yes - open to Australia (Melbourne, Sydney), New Zealand (anywhere), China (Shanghai, Shenzhen, Beijing), Singapore, Hong Kong, or Remote APAC"
    },

    "accessibility_context": {
        "condition": "Albinism resulting in 5% vision (legally blind)",
        "media_documentation": "Openly documented in Forbes, TEDx, and multiple industry articles - easily discoverable via Google search. This is public information but not professionally defining.",
        "professional_impact": "Zero impact on work performance. Ran international photogrammetry expeditions across multiple countries, built Lumiere Award-winning VR experiences, architected 60+ microservice platforms, achieved sub-millimeter accuracy on 40+ billion point datasets. Demonstrates exceptional adaptability, spatial reasoning, and problem-solving despite visual limitations.",
        "workplace_accommodations": {
            "required": [
                "Dark mode / high contrast display settings (standard on all modern OS)",
                "Standing desk (common in modern tech offices)"
            ],
            "note": "All accommodations are standard equipment in modern tech offices - nothing specialized or expensive required."
        },
        "disclosure_strategy": {
            "instruction": "Don't lead with it, but mention strategically when:",
            "scenarios": [
                "Directly asked about accommodations or accessibility needs",
                "Application asks about diversity or overcoming challenges",
                "Role is with a company that values transparency (they'll Google anyway)",
                "Strategic to demonstrate resilience and problem-solving under constraints"
            ],
            "framing": "Always frame positively - this has never been a limitation, only demonstrates adaptability. Focus on achievements despite constraints, not the constraint itself."
        }
    },

    "profile_links": {
        "linkedin_url": "https://linkedin.com/in/simon-che-de-boer-2a49386a",
        "github_url": "https://github.com/thesystemera",
        "portfolio_url": "https://www.realityvirtual.co/, plair.live, moneyprinter.live"
    }
}

CV_FULL_TEXT = """
SIMON CHE DE BOER
Creative Technologist | AI Solutions Architect | Founder
Auckland, New Zealand | linkedin.com/in/simon-che-de-boer-2a49386a

PROFESSIONAL SUMMARY
A globally recognised Creative Technologist and R&D Lead with over a decade of experience defining the bleeding edge of Digital Heritage, Virtual Reality, and Generative AI.
Formerly the Founder & CTO of realityvirtual.co, I led the teams responsible for the world's most significant high-fidelity VR experiences, including the Lumiere Award-winning digitalization of Queen Nefertari's Tomb.
My core strength is Systemic Logic: bridging the gap between Art, Science, and Code.
With a background in Audio Engineering (DSP), I approach software architecture like signal flow—building efficient, modular, and scalable systems.
Most recently, I have pioneered an AI-Augmented Development workflow delivering production-scale platforms at startup velocity.
Previously scaled realityvirtual.co to an 11-person studio recognised globally for defining photogrammetry standards in VR.
In 2024-2025, I architected and deployed two enterprise-grade platforms (PLAiR + MoneyPrinter)—both built with production security standards, DRY architecture, comprehensive error handling, and deployment-ready infrastructure.
Work that traditionally requires teams of 10-20 engineers and 12-18 months, I delivered in 3-6 months through systematic AI orchestration combined with rigorous engineering principles.

CURRENT VENTURE
Founder & Lead Architect | PLAiR (Personalised Localised Adaptive Interactive Radio)
2024 – Present | v1: May-Nov 2024 | v2: Oct-Dec 2025 (3-month rebuild)
Architected and built the next generation of adaptive audio streaming—originally conceptualized as a 2010 thesis.
Built production v1 (May-Nov 2024) which secured board-level interest from industry leaders.
When Spotify deprecated their API in November 2024, pivoted to financial analytics before returning to rebuild PLAiR from the ground up (Oct-Dec 2025) as a fully independent platform with multi-AI orchestration.
The Product: A fully autonomous, AI-driven radio platform that generates personalized, localized, and interactive audio streams for users.
Unlike traditional streaming services, PLAiR adapts content in real-time based on location, time of day, and listener preferences—creating a unique "radio station" for each user.
Production Architecture: 60+ microservices backend with strict DRY principles, comprehensive error handling, and security-first design.
7-layer intelligent caching (Redis, CDN, Local) achieving 60-70% cost reduction. Semantic vector search (pgvector) serving 1M+ embeddings at <200ms latency.
Containerized deployment with rate limiting, auth middleware, and fault-tolerant architecture.
Multi-AI Orchestration: Integrated five AI systems (Claude for LLM, ElevenLabs for TTS, Whisper for STT, Demucs for source separation, Suno for music generation) with intelligent 7-layer caching architecture achieving 60-70% operational cost reduction.
Advanced Frontend: Implemented GLSL shader-based audio visualizations, dual-buffer audio engine with gapless crossfading, 3D parallax artwork rendering (AI-generated depth maps), and multi-device WebSocket synchronization with <30ms latency.
Commercial Validation: Secured board-level interest from industry titans including Shaquille O'Neal and Terry Ellis.
Development was impacted by Spotify's API deprecation, requiring platform pivot.
Current Status: Live deployment at plair.live, demonstrating superior localization and interactivity features compared to current market leaders.

EXPERIENCE
Founder | MoneyPrinter.live (AI Financial Analytics Platform)
January – June 2025
Pivoted to financial technology following Spotify's API deprecation, building a secure, production-ready financial analytics platform that achieved 65% movement-weighted accuracy on directional predictions—demonstrating hedge fund level performance on the industry-standard metric.
Platform featured real-time data pipelines, comprehensive error handling, rate limiting, and fault-tolerant architecture, but capital constraints prevented scaling to sustainable operations.
Production Engineering: Built with API versioning and deprecation patterns, comprehensive error handling, rate limiting and auth middleware, containerized deployment (Docker), and strict separation of concerns—demonstrating enterprise patterns, not prototype code.
High-frequency sentiment analysis: Real-time market intelligence extraction across multiple data sources using LLM-based pattern recognition with fault-tolerant architecture.
Predictive modeling: 65% movement-weighted accuracy significantly exceeds baseline (50%) and demonstrates institutional-grade signal generation for market intelligence.
Platform architecture: Built complete trading signal generation system with real-time data processing, demonstrating cross-domain AI expertise from audio streaming to financial analytics.

Principal Developer & Researcher (Stealth/Independent)
2020 – 2022
Transitioned from VR infrastructure to pure AI/ML R&D during the global travel restriction period.
DeepMirror & DeepPBR: Developed proprietary AI tools for volumetric teleconferencing and PBR (Physically Based Rendering) material generation.
DeepMirror enabled real-time 3D reconstruction from standard webcams, while DeepPBR automated the extraction of material properties (albedo, roughness, metallic) from photogrammetry datasets.
BigPipe: Engineered an automated data pipeline tool to streamline the processing of massive 3D datasets (40+ billion point clouds), utilizing custom GLSL shader-based processing with geometry and texture inpainting, leveraging deepPBR for map generation, and Python automation to reduce processing time from weeks to hours—enabling real-time manipulation of datasets 50x larger than any prior environmental photogrammetry project.
Custom Model Training: Designed and trained neural network architectures for DeepPBR's material extraction and BigPipe's automated processing pipelines.
More recently, developed custom models to enhance AI-generated music (Suno) to broadcast quality standards.

Founder & CTO | realityvirtual.co
2014 – 2020
Founded and scaled an internationally recognised 11-person studio specialising in photogrammetry and volumetric capture for VR.
Led engineering, creative, and production teams delivering award-winning cultural heritage experiences for partners including the Getty Conservation Institute and Egyptian Ministry of Antiquities.
Notable Achievements
Lumiere Award Winner (2020): Received the Advanced Imaging Society's Lumiere Award for "Best VR Educational Experience" for Nefertari: Journey to Eternity — competing against major studios including DreamWorks and Disney.
Epic Games Mega Grant Recipient: One of only two New Zealand companies awarded funding from Epic's $100M USD global innovation fund, recognizing our contributions to real-time rendering and photogrammetry workflows.
Meta Real-World Encapsulation Program (2022): Selected as one of four companies worldwide for Meta's million-dollar real-world encapsulation program.
Completed pilot phase, though resource constraints following New Zealand's 2.5-year border closure prevented securing the full contract.
Company Scaling: Grew realityvirtual.co from solo founder to 11-person team over 6 years, managing engineering, creative, and production staff across multiple international projects simultaneously.
Technical Innovations
Proprietary Photogrammetry Pipeline: Led engineering team to develop a custom workflow achieving sub-millimeter accuracy across 40+ billion point datasets—50x larger than any prior environmental photogrammetry project.
Featured by Epic Games as the "gold standard" for photorealistic VR.
Cultural Heritage Partnerships: Managed cross-functional delivery collaborating with the Getty Conservation Institute and Egyptian Ministry of Antiquities to digitally preserve Queen Nefertari's Tomb (Valley of the Queens, Egypt) at millimeter-level accuracy using 4,000+ high-resolution photographs.
Industry Partnerships: Direct collaboration with NVIDIA, Epic Games (Unreal Engine), and Unity Technologies to push the boundaries of real-time rendering, GPU optimisation, and large-scale data processing.
DeepPBR Technology: Developed AI-powered material extraction system using four custom GANs to automatically generate PBR textures (albedo, roughness, normals, displacement) from single photographs. Included temporal video processing for virtual studio production and enterprise blackbox solutions for major studios.
Select Projects
Nefertari: Journey to Eternity — Steam/Viveport release with 92% positive reviews (233 reviews)
Tutankhamun: Enter the Tomb — Created for CuriosityStream
The Homestead — Sir James Wallace Art Gallery (Auckland)
MANA VR — Indigenous Māori cultural preservation project
He Tohu VR — New Zealand constitutional documents (Treaty of Waitangi) experience in partnership with Archives NZ and National Library
Large Hadron Collider — CERN collaboration for scientific facility digitization
EPFL (École Polytechnique Fédérale de Lausanne) — 3-month residency in Switzerland developing real-time data visualization systems for large-scale projection installations
New Zealand Parliament — Full debating chamber photogrammetry capture
Sky Tower Auckland — Commercial landmark VR experience

INDUSTRY PARTNERSHIPS & COLLABORATORS
Throughout realityvirtual.co's operations (2014-2020), established strategic partnerships and received recognition from leading technology companies and cultural institutions:
Technology Partners: Epic Games (Mega Grant recipient, featured as "gold standard" for photogrammetry), NVIDIA (Featured at GDC 2017, GPU optimization collaboration, enterprise blackbox hardware for deepPBR), Meta/Facebook Reality Labs (Real-World Encapsulation Program - 1 of 4 companies worldwide), Amazon Web Services (cloud infrastructure partnership), Unity Technologies (real-time rendering pipelines), Autodesk, RealityCapture/Capturing Reality, HTC & HP (hardware partners), Cesium/Bentley Systems (3D geospatial platform collaboration).
Cultural & Government Partners: Getty Conservation Institute, Egyptian Ministry of Antiquities, CERN/EPFL, Archives New Zealand & National Library, Pou Kapua Creations (MANA VR and He Tohu VR co-development), Wallace Trust.
Distribution Partners: CuriosityStream, Steam/Viveport, IMG Productions.

SPEAKING ENGAGEMENTS & INDUSTRY PRESENCE
Conference Presentations: TEDxAuckland 2019 ("Backing up the planet: Digitising culture, history and heritage"), SXSW 2019 (photogrammetry and VR for cultural heritage), State of Art Academy 2018 Venice (technical deep-dive on deep learning pipelines for photogrammetry, covering deepPBR's four-GAN architecture), GDC 2017 NVIDIA Booth (MANA VR technology demo with Pou Kapua Creations), Cesium Conference (guest speaker on 3D geospatial applications and large-scale point cloud management).
Podcast & Interview Appearances: RiVR Podcast (photogrammetry workflows and VR production pipelines), CG Pro Podcast (AI-enhanced photogrammetry and virtual production), 80.lv Technical Articles (multiple featured articles and technical breakdowns of photogrammetry innovations).

SELECT HONOURS & MEDIA
Lumiere Award Winner (2020): Advanced Imaging Society - Best VR Educational Experience
Forbes Feature (2019): "Unreal Archaeology - How The Ancient World Is Being Recreated In Virtual Reality"
TEDx Speaker (2019): "Backing up the planet: Digitising culture, history and heritage" — TEDxAuckland
TechCrunch Feature (2018): Highlighted for pioneering volumetric photogrammetry workflows
Unreal Engine Spotlight: Featured by Epic Games for setting photogrammetry benchmarks
RoadToVR Coverage (2018): "Photorealistic VR Tour 'Nefertari: Journey to Eternity' Takes You Deep into a 3,000 Year-old Egyptian Tomb"
80.lv Technical Features: Multiple in-depth technical articles on deepPBR and advanced photogrammetry techniques
ScoutVR Coverage: Featured work demonstrating VR's potential for cultural heritage preservation
eLearningInside: Major profile piece on photogrammetry innovation and educational VR applications

TECHNICAL SKILLS
AI & Orchestration: Expert in "AI-Augmented Architecture" using Claude Sonnet 4, GPT-4, and local LLMs (Ollama) to orchestrate full-stack development.
Specialized in prompt engineering for code generation, system design, and rapid prototyping.
Systems Architecture & Code Orchestration: Expert-level comprehension across Python, JavaScript/React, GLSL, C++ - specialized in AI-augmented development where I architect systems, orchestrate code generation, and perform expert-level review/correction. Read/audit proficient across all listed languages.
Full-Stack Development: FastAPI, React, Node.js, REST APIs, WebSocket protocols, Docker containerization, Redis, PostgreSQL.
3D & VR: Unreal Engine 5 (Expert-level Blueprints + C++), Unity, Maya, Houdini, Substance Painter/Designer, RealityCapture, Agisoft Metashape, Volumetric Video Pipelines.
Audio/DSP: Deep understanding of signal flow, node-based logic (Max/MSP legacy), and Digital Signal Processing (Cubase/Nuendo background).
Experience with real-time audio routing and procedural generation.
Computer Vision: OpenCV, custom photogrammetry pipelines, real-time 3D reconstruction, volumetric capture processing.
Data & ML: Experience with PyTorch, TensorFlow, GANs (Generative Adversarial Networks), neural rendering techniques, and LLM fine-tuning.
Practical experience designing and training custom model architectures for domain-specific applications including material extraction, audio enhancement, and automated 3D processing pipelines.

SUPPLEMENTARY SKILLS & EXPERIENCE
Creative Production: Proficient in Adobe Premiere, After Effects, Blender - extensive video production background supporting VR content creation and marketing.
Additional Technical: PHP, MySQL, and various other databases and frameworks accumulated over a decade of diverse projects.
Music: Released 3 albums (~2010-2011), demonstrating creative background and complementing audio engineering expertise.
Breadth: Prolific across many tools and technologies beyond formal CV - extensive hands-on experience with a wide range of creative and technical tools.

MEDIA & LINKS
Company Website (Showcase): https://www.realityvirtual.co/
Forbes: Unreal Archaeology - How The Ancient World Is Being Recreated In Virtual Reality
TEDx Talk: Backing up the planet: Digitising culture, history and heritage
Unreal Engine Feature: Unreal Engine preserves New Zealand culture with hyper-real imagery
TechCrunch: Volumetric photogrammetry -- big words, bigger impact on VR
RoadToVR: Photorealistic VR Tour 'Nefertari: Journey to Eternity'
Nefertari Project: Steam Store Page (92% positive / 233 reviews)
PLAiR Platform: plair.live
MoneyPrinter Platform: moneyprinter.live
80.lv - deepPBR Technical Article: Making PBR Textures from Photos
State of Art Academy Interview (2018): Venice Technical Deep-Dive on Deep Learning for Photogrammetry
eLearningInside Profile: Capturing the Past in Virtual Reality – An Interview with Simon Che de Boer
Cesium Guest Profile: Simon Che de Boer – Geospatial 3D Expert
"""