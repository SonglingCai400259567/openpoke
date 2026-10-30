import json, re, random, collections
from pathlib import Path
OUT=Path(__file__).resolve().parent
OUT.mkdir(parents=True,exist_ok=True)
workflows=[]
primary=[]
def W(key,title,typ,summary,entities,q1,q2,h1=None,h2=None):
    w=dict(key=key,title=title,task_type=typ,summary=summary,entities=entities)
    workflows.append(w)
    primary.append((w,q1,q2,h1 if h1 is not None else entities,h2 if h2 is not None else entities))

# 40 curated, close but genuinely distinct workflows; each has two hand-written continuation queries.
W('alice_auto_101','Alice Sedan Coverage Quote AUTO-101','email','Compare insurer rates for Alice 2022 sedan under AUTO-101',{'contact':'Alice','case_id':'AUTO-101'},'Did the broker reply to Alice about AUTO-101?','Continue checking the sedan insurance estimate AUTO-101 for Alice.')
W('alice_auto_104','Alice Motorcycle Coverage Quote AUTO-104','email','Obtain motorcycle policy premium for Alice under AUTO-104',{'contact':'Alice','case_id':'AUTO-104'},'Any updates on Alice motorcycle quote AUTO-104?','Follow up on the bike insurance request AUTO-104 with Alice.')
W('alice_home_102','Alice Condo Renewal HOME-102','email','Renew Alice condo coverage HOME-102 ahead of the annual term',{'contact':'Alice','case_id':'HOME-102'},'Has Alice approved renewal HOME-102?','Please continue the HOME-102 condominium renewal.')
W('alice_claim_103','Alice Windshield Claim CLAIM-103','email','Track insurer approval for Alice windshield replacement claim CLAIM-103',{'contact':'Alice','case_id':'CLAIM-103'},'Check the latest on Alice windshield claim CLAIM-103.','Did the adjuster answer about CLAIM-103?')
W('bob_auto_201','Bob EV Insurance Quote AUTO-201','email','Price electric vehicle coverage for Bob policy quote AUTO-201',{'contact':'Bob','case_id':'AUTO-201'},'What did Bob say about AUTO-201 EV coverage?','Resume the electric-car premium discussion for Bob AUTO-201.')
W('bob_contract_meeting','Bob Vendor Contract Meeting MTG-210','calendar','Coordinate Bob vendor contract negotiation on calendar event MTG-210',{'contact':'Bob','meeting_id':'MTG-210'},'Move the Bob contract meeting MTG-210 to Friday.','Has Bob confirmed time for MTG-210?')
W('carol_offer_pine','Carol Pine Labs Offer OFFER-301','email','Review Carol job offer from Pine Labs reference OFFER-301',{'contact':'Carol','offer_id':'OFFER-301','company':'Pine Labs'},'Any changes to the Pine Labs offer OFFER-301 from Carol?','Check Carol compensation note for Pine Labs OFFER-301.')
W('carol_offer_cedar','Carol Cedar Studio Offer OFFER-302','email','Negotiate Carol employment package at Cedar Studio reference OFFER-302',{'contact':'Carol','offer_id':'OFFER-302','company':'Cedar Studio'},'Did Carol respond about Cedar Studio OFFER-302?','Continue the Cedar Studio job offer discussion OFFER-302.')
W('david_invoice_404','David Consulting Invoice INV-404','email','Collect payment receipt for David consulting invoice INV-404',{'contact':'David','invoice_id':'INV-404'},'Has David attached the receipt for INV-404?','Follow up on the consulting bill INV-404 with David.')
W('david_invoice_405','David Equipment Invoice INV-405','email','Verify David equipment reimbursement invoice INV-405',{'contact':'David','invoice_id':'INV-405'},'Any update from David on INV-405 equipment invoice?','Check whether reimbursement INV-405 was approved.')
W('emily_flight_ac123','Emily Toronto Flight AC123','research','Monitor Emily Toronto arrival on flight AC123',{'contact':'Emily','flight_number':'AC123'},'Is Emily flight AC123 delayed right now?','Continue monitoring AC123 arrival for Emily.')
W('emily_flight_ws456','Emily Calgary Flight WS456','research','Track Emily Calgary flight WS456 and baggage connections',{'contact':'Emily','flight_number':'WS456'},'Check WS456 for Emily today.','How is Emily Calgary flight WS456 doing?')
W('nova_digest','Project NOVA AI Weekly Digest','research','Summarize weekly machine learning papers for NOVA project',{'project':'NOVA','report_id':'NOVA-WEEKLY'},'Continue this week NOVA machine-learning roundup.','Generate the next NOVA-WEEKLY research digest.')
W('comet_report','Project COMET Risk Report','research','Maintain COMET project monthly operational risk report COMET-MONTHLY',{'project':'COMET','report_id':'COMET-MONTHLY'},'Update the COMET-MONTHLY risk summary.','Are the COMET project risks ready for this month report?')
W('orion_review','Project ORION Design Review','research','Compile ORION architecture design-review findings ORION-REV',{'project':'ORION','report_id':'ORION-REV'},'Add the latest notes to ORION-REV.','Follow up on the ORION architecture review.')
W('atlas_api','Project ATLAS Backend Migration ISSUE-426','coding','Migrate ATLAS API endpoints for backend issue ISSUE-426',{'project':'ATLAS','issue_id':'ISSUE-426'},'Check blockers on ATLAS backend ISSUE-426.','Continue the endpoint migration issue ISSUE-426.')
W('atlas_mobile','Project ATLAS Mobile Login ISSUE-427','coding','Repair mobile sign-in behavior in ATLAS ISSUE-427',{'project':'ATLAS','issue_id':'ISSUE-427'},'Has the ATLAS mobile login bug ISSUE-427 been fixed?','Review the latest patch for ISSUE-427 authentication.')
W('henry_support_301','Henry Printer Support TCK-301','support','Troubleshoot Henry printer connectivity ticket TCK-301',{'contact':'Henry','ticket_id':'TCK-301'},'Any progress with Henry printer ticket TCK-301?','Continue resolving TCK-301 printer connection.')
W('henry_support_302','Henry VPN Support TCK-302','support','Investigate Henry remote VPN access ticket TCK-302',{'contact':'Henry','ticket_id':'TCK-302'},'Follow up on Henry VPN incident TCK-302.','Did IT respond to Henry about TCK-302?')
W('grace_paris','Grace Paris Itinerary TRIP-501','travel','Plan Grace Paris museum itinerary TRIP-501',{'contact':'Grace','trip_id':'TRIP-501'},'Update Grace Paris itinerary TRIP-501.','Did we reserve the museum visit for TRIP-501?')
W('grace_tokyo','Grace Tokyo Itinerary TRIP-502','travel','Arrange Grace Tokyo city excursions TRIP-502',{'contact':'Grace','trip_id':'TRIP-502'},'Review the Tokyo day plan TRIP-502 for Grace.','Continue planning Grace Japan itinerary TRIP-502.')
W('frank_hotel','Frank Montreal Hotel BOOK-601','travel','Track Frank Montreal lodging reservation BOOK-601',{'contact':'Frank','booking_id':'BOOK-601'},'Is Frank Montreal hotel BOOK-601 confirmed?','Follow up on accommodation BOOK-601 for Frank.')
W('ivy_order_831','Ivy Camera Shipment ORD-831','research','Monitor Ivy camera equipment order ORD-831 shipping',{'contact':'Ivy','order_id':'ORD-831'},'Where is Ivy camera order ORD-831?','Check the latest courier status for ORD-831.')
W('ivy_order_832','Ivy Lens Return ORD-832','research','Process Ivy lens return and refund tracking ORD-832',{'contact':'Ivy','order_id':'ORD-832'},'Did Ivy get the refund for ORD-832?','Continue tracking the lens return ORD-832.')
W('jack_thesis','Jack Thesis Review THESIS-701','research','Edit Jack thesis methodology section THESIS-701',{'contact':'Jack','document_id':'THESIS-701'},'Please revise the methods chapter for THESIS-701.','Any feedback on Jack thesis THESIS-701?')
W('jack_supervisor_meeting','Jack Supervisor Meeting MTG-702','calendar','Coordinate Jack thesis supervisor discussion MTG-702',{'contact':'Jack','meeting_id':'MTG-702'},'Reschedule Jack supervisor meeting MTG-702.','Has the advisor accepted MTG-702?')
W('kate_tax','Kate Tax Filing TAX-801','research','Organize Kate personal tax return documents TAX-801',{'contact':'Kate','filing_id':'TAX-801'},'Which receipts remain for Kate TAX-801?','Check progress on personal tax filing TAX-801.')
W('kate_budget','Kate Team Budget BUD-802','research','Review Kate department operating budget BUD-802',{'contact':'Kate','budget_id':'BUD-802'},'Continue reconciling team budget BUD-802.','Are Kate department expenses ready for BUD-802?')
W('liam_hvac','Liam HVAC Repair JOB-901','support','Coordinate Liam furnace inspection work order JOB-901',{'contact':'Liam','work_order_id':'JOB-901'},'Has the technician confirmed Liam HVAC JOB-901?','Continue scheduling furnace repair JOB-901.')
W('liam_window','Liam Window Repair JOB-902','support','Follow up on Liam window crank replacement JOB-902',{'contact':'Liam','work_order_id':'JOB-902'},'Any response about Liam window JOB-902?','Track the replacement parts for JOB-902.')
W('maya_conference','Maya Tech Conference EVT-110','calendar','Arrange Maya technology conference presentation EVT-110',{'contact':'Maya','event_id':'EVT-110'},'Has Maya confirmed the conference slot EVT-110?','Update the speaking schedule EVT-110.')
W('maya_webinar','Maya Online Webinar EVT-111','calendar','Plan Maya virtual product webinar EVT-111',{'contact':'Maya','event_id':'EVT-111'},'Can we change Maya webinar EVT-111 time?','Follow up on virtual event EVT-111.')
W('nora_m31','Nora Andromeda Image Session ASTRO-201','research','Process Nora Andromeda stacked image session ASTRO-201',{'contact':'Nora','session_id':'ASTRO-201'},'Continue calibrating M31 frames from ASTRO-201.','How did Nora Andromeda session ASTRO-201 stack?')
W('nora_moon','Nora Lunar Stack Session ASTRO-202','research','Sharpen Nora moon imaging session ASTRO-202',{'contact':'Nora','session_id':'ASTRO-202'},'Revisit lunar stacking for ASTRO-202.','Review moon wavelet settings for Nora ASTRO-202.')
W('oliver_backend_job','Oliver Backend Application JOB-210','email','Follow up on Oliver backend engineering job application JOB-210',{'contact':'Oliver','application_id':'JOB-210'},'Has Oliver replied about backend role JOB-210?','Continue the server engineer application JOB-210.')
W('oliver_ai_job','Oliver AI Application JOB-211','email','Track Oliver machine-learning engineer position JOB-211',{'contact':'Oliver','application_id':'JOB-211'},'Any interview news from Oliver for JOB-211?','Follow up on Oliver machine-learning opening JOB-211.')
W('patricia_vendor_acme','Patricia Acme Contract CTR-310','email','Negotiate Patricia supplier agreement with Acme CTR-310',{'contact':'Patricia','company':'Acme','contract_id':'CTR-310'},'Continue Acme contract CTR-310 with Patricia.','Did Patricia approve the CTR-310 terms?')
W('patricia_vendor_zen','Patricia Zenith Contract CTR-311','email','Review Patricia distribution terms for Zenith CTR-311',{'contact':'Patricia','company':'Zenith','contract_id':'CTR-311'},'Did Zenith contract CTR-311 get signed?','Follow up with Patricia on the Zenith agreement CTR-311.')
W('quinn_launch','Quinn Product Launch PRJ-410','research','Coordinate Quinn product marketing launch PRJ-410',{'contact':'Quinn','project':'PRJ-410'},'Update the PRJ-410 launch checklist.','Continue planning Quinn product rollout PRJ-410.')
W('quinn_campaign','Quinn Holiday Campaign PRJ-411','research','Analyze Quinn winter advertising campaign PRJ-411',{'contact':'Quinn','project':'PRJ-411'},'Check conversion metrics for PRJ-411 campaign.','Follow up on the holiday promotion PRJ-411.')
W('rachel_course','Rachel Security Training CRS-510','research','Track Rachel cybersecurity training completion CRS-510',{'contact':'Rachel','course_id':'CRS-510'},'How far is Rachel with security course CRS-510?','Continue the CRS-510 training checklist.')
W('rachel_webinar','Rachel Python Workshop CRS-511','calendar','Organize Rachel Python workshop schedule CRS-511',{'contact':'Rachel','course_id':'CRS-511'},'Change the Python workshop CRS-511 timeslot.','Check registration for Rachel course CRS-511.')

assert len(primary)==42,(len(primary),[w['key'] for w in workflows])
# 158 hard-negative but non-identical workflow records. They are contextually plausible and have unique object references.
people=['Alice','Bob','Carol','David','Emily','Frank','Grace','Henry','Ivy','Jack','Kate','Liam','Maya','Nora','Oliver','Patricia','Quinn','Rachel','Sam','Tina']
domains=[
 ('email','Equipment Coverage','equipment insurance policy','policy_id','EQP'),
 ('email','Invoice Follow-up','consulting services invoice','invoice_id','INV'),
 ('calendar','Review Meeting','quarterly planning meeting','meeting_id','MTG'),
 ('support','Helpdesk Issue','user device access incident','ticket_id','TCK'),
 ('research','Shipment Tracking','parcel delivery status','order_id','ORD'),
 ('research','Research Brief','sector technology research summary','report_id','RPT'),
 ('travel','Holiday Plan','weekend travel itinerary','trip_id','TRP'),
 ('coding','Application Maintenance','client application defect','issue_id','ISS'),
]
for di,(typ,topic,desc,id_key,prefix) in enumerate(domains):
 for pi,person in enumerate(people):
  if len(workflows)>=200:break
  idx=di*20+pi
  ref=f'{prefix}-X{idx+1000:04d}'
  workflows.append(dict(key=f'distractor_{di}_{pi}', title=f'{person} {topic} {ref}',task_type=typ,
   summary=f'Continue {person} {desc} for reference {ref}; separate internal workflow',
   entities={'contact':person,id_key:ref}))
assert len(workflows)==200,len(workflows)

actions=[]
def add(query,action,target_key=None,intent='unspecified',entities=None,task_type=None,group='general',rationale='',difficulty='medium'):
  assert action in ('RESUME','CREATE','CLARIFY')
  # The oracle hint must never contain a value invisible in the current user utterance.
  # Any richer conversational context would need to be included explicitly in the case.
  entities = {k: v for k, v in (entities or {}).items() if str(v).casefold() in query.casefold()}
  actions.append(dict(case_id=f'V2-{len(actions)+1:03d}',query=query,expected_action=action,target_key=target_key,
   intent=intent,entity_hints=entities if entities is not None else {},task_type_hint=task_type,
   group=group,rationale=rationale,difficulty=difficulty))

for w,q1,q2,h1,h2 in primary:
 add(q1,'RESUME',w['key'],'continue',h1,w['task_type'],'exact_reference',
     'The user refers to the existing internal workflow by a matching unique reference.','easy')
 add(q2,'RESUME',w['key'],'continue',h2,w['task_type'],'semantic_continuation',
     'The request continues the same task and business object recorded by the workflow.','medium')
assert len(actions)==84
# CREATE: external object references NOT PRESENT in the internal workflow registry, despite existing-sounding language.
external_missing=[
 ('Alice','quote AUTO-991','case_id','AUTO-991','email','Could you check the insurer reply about Alice quote AUTO-991?'),
 ('Bob','invoice INV-991','invoice_id','INV-991','email','Please continue following up on Bob invoice INV-991.'),
 ('Carol','employment offer OFFER-991','offer_id','OFFER-991','email','Has Carol answered my question about job offer OFFER-991?'),
 ('David','invoice INV-992','invoice_id','INV-992','email','Could you check whether David paid invoice INV-992?'),
 ('Emily','flight QF991','flight_number','QF991','research','Track Emily flight QF991 for me.'),
 ('Frank','hotel booking BOOK-991','booking_id','BOOK-991','travel','Please look up Frank hotel confirmation BOOK-991.'),
 ('Grace','itinerary TRIP-991','trip_id','TRIP-991','travel','Help continue arrangements for Grace itinerary TRIP-991.'),
 ('Henry','support ticket TCK-991','ticket_id','TCK-991','support','Can you check Henry helpdesk ticket TCK-991?'),
 ('Ivy','package ORD-991','order_id','ORD-991','research','Where has Ivy package ORD-991 reached?'),
 ('Jack','draft THESIS-991','document_id','THESIS-991','research','Review the latest Jack draft THESIS-991.'),
 ('Kate','tax filing TAX-991','filing_id','TAX-991','research','Please organize the missing items for Kate tax filing TAX-991.'),
 ('Liam','repair request JOB-991','work_order_id','JOB-991','support','Check with the vendor about Liam repair JOB-991.'),
 ('Maya','conference booking EVT-991','event_id','EVT-991','calendar','Has Maya confirmed conference session EVT-991?'),
 ('Nora','astrophotography session ASTRO-991','session_id','ASTRO-991','research','Continue processing the images from Nora session ASTRO-991.'),
 ('Oliver','application JOB-991','application_id','JOB-991','email','Any reply from Oliver about application JOB-991?'),
 ('Patricia','supplier agreement CTR-991','contract_id','CTR-991','email','Check whether Patricia signed supplier agreement CTR-991.'),
 ('Quinn','campaign PRJ-991','project','PRJ-991','research','Look into the status of Quinn campaign PRJ-991.'),
 ('Rachel','training CRS-991','course_id','CRS-991','research','Please check Rachel progress on training CRS-991.'),
 ('Sam','support ticket TCK-992','ticket_id','TCK-992','support','Can you follow up on Sam unresolved support case TCK-992?'),
 ('Tina','trip TRIP-992','trip_id','TRIP-992','travel','Find out whether Tina itinerary TRIP-992 was updated.'),
 ('Alice','new external complaint EXT-993','case_id','EXT-993','email','I need an update on Alice complaint EXT-993.'),
 ('Bob','vehicle policy AUTO-994','case_id','AUTO-994','email','Resume checking Bob vehicle policy AUTO-994.'),
 ('Carol','rental invoice INV-994','invoice_id','INV-994','email','Look up Carol rental invoice INV-994 and ask for a receipt.'),
 ('David','calendar invitation MTG-994','meeting_id','MTG-994','calendar','Confirm whether David accepted invitation MTG-994.'),
 ('Emily','travel claim CLAIM-994','case_id','CLAIM-994','email','Check the status of Emily baggage claim CLAIM-994.'),
 ('Frank','research request RPT-994','report_id','RPT-994','research','Pick up the research request RPT-994 for Frank.'),
 ('Grace','refund ORD-994','order_id','ORD-994','research','Can you investigate Grace refund ORD-994?'),
 ('Henry','access problem TCK-994','ticket_id','TCK-994','support','Follow up on Henry access problem TCK-994.'),
 ('Ivy','camera delivery ORD-995','order_id','ORD-995','research','Continue tracking Ivy camera shipment ORD-995.'),
 ('Jack','review session MTG-995','meeting_id','MTG-995','calendar','Check the date of Jack review session MTG-995.'),
]
for name,desc,key,value,typ,q in external_missing:
 add(q,'CREATE',None,'continue',{ 'contact':name,key:value},typ,'missing_internal_external_reference',
    'The external object may exist, but no internal OpenPoke workflow represents it; create an internal tracking workflow.', 'hard')
assert len(actions)==114
# CREATE: new independent scope with similar existing workflow; 25 carefully authored cases.
new_scope=[
 ('Please start a separate insurance review for Alice new electric scooter.',{'contact':'Alice'},'email'),
 ('Compare a third job offer from Lakeshore Tech for Carol, separate from Pine and Cedar.',{'contact':'Carol','company':'Lakeshore Tech'},'email'),
 ('Set up a distinct insurance quote for Bob new pickup truck.',{'contact':'Bob'},'email'),
 ('Create another invoice chase for David catering purchase INV-505.',{'contact':'David','invoice_id':'INV-505'},'email'),
 ('Arrange a new travel reminder for Emily flight LH706.',{'contact':'Emily','flight_number':'LH706'},'research'),
 ('I want a different Paris trip for Grace next spring, not TRIP-501.',{'contact':'Grace'},'travel'),
 ('Start a separate monitor for Frank train reservation TRAIN-801.',{'contact':'Frank','booking_id':'TRAIN-801'},'travel'),
 ('Help Henry investigate a new keyboard problem, not either earlier helpdesk ticket.',{'contact':'Henry'},'support'),
 ('Track Ivy new tripod order ORD-910, not the camera shipment.',{'contact':'Ivy','order_id':'ORD-910'},'research'),
 ('Book Jack a new committee meeting unrelated to MTG-702.',{'contact':'Jack'},'calendar'),
 ('Prepare Kate next-year tax return rather than continuing TAX-801.',{'contact':'Kate'},'research'),
 ('Open an unrelated plumbing repair follow-up for Liam.',{'contact':'Liam'},'support'),
 ('Set up a new online keynote for Maya distinct from EVT-110 and EVT-111.',{'contact':'Maya'},'calendar'),
 ('Process Nora new Jupiter image set ASTRO-220, separate from the Moon and M31.',{'contact':'Nora','session_id':'ASTRO-220'},'research'),
 ('Draft an application for Oliver to a different role, JOB-410.',{'contact':'Oliver','application_id':'JOB-410'},'email'),
 ('Review a new Patricia contract with a third supplier, Meridian.',{'contact':'Patricia','company':'Meridian'},'email'),
 ('Create a fresh analytics task for Quinn spring campaign PRJ-420.',{'contact':'Quinn','project':'PRJ-420'},'research'),
 ('Organize Rachel separate cloud networking workshop CRS-620.',{'contact':'Rachel','course_id':'CRS-620'},'calendar'),
 ('Please launch the first task for a new project named ECLIPSE.',{'project':'ECLIPSE'},'research'),
 ('Open a separate architectural review for Project SOLSTICE.',{'project':'SOLSTICE'},'research'),
 ('I need a second analysis on NOVA, focused on security rather than its weekly AI digest.',{'project':'NOVA'},'research'),
 ('Create an independent mobile crash issue for ATLAS; do not reuse ISSUE-427.',{'project':'ATLAS'},'coding'),
 ('Prepare a new monthly COMET finance report, not the operational risk report.',{'project':'COMET'},'research'),
 ('Start a completely unrelated marketing follow-up for Quinn new customer segment.',{'contact':'Quinn'},'research'),
 ('Please initiate a separate cloud cost review for Project ORION.',{'project':'ORION'},'research'),
]
for i,(q,ents,typ) in enumerate(new_scope):
 add(q,'CREATE',None, 'new' if i%2==0 else 'unspecified',ents,typ,'new_scope_same_entity',
    'A distinct task objective or business object is requested; internal workflow identity must not be reused.', 'hard')
assert len(actions)==139
# CREATE: entirely new work that is actionable; 16 items to reach total 71 creates.
novel=[
 ('Summarize the public earnings report of Helio Robotics.',{},'research'),
 ('Plan a beginner hiking route around a mountain lake for Saturday.',{},'travel'),
 ('Draft a customer support reply for a new contact named Uma.',{'contact':'Uma'},'email'),
 ('Find and compare three standing-desk models for my office.',{},'research'),
 ('Organize a kickoff agenda for Project MISTRAL.',{'project':'MISTRAL'},'calendar'),
 ('Help me write an introduction email to an architect named Victor.',{'contact':'Victor'},'email'),
 ('Investigate a new error in my data ingestion pipeline: PIPE-700.',{'issue_id':'PIPE-700'},'coding'),
 ('Create a reminder workflow to check my gym membership renewal.',{},'calendar'),
 ('Research how meteor showers are photographed with wide lenses.',{},'research'),
 ('Prepare a checklist for replacing a laptop battery.',{},'research'),
 ('Draft a first-time vendor inquiry to Willow Supplies.',{'company':'Willow Supplies'},'email'),
 ('Compare costs of a brand-new conference trip to Halifax.',{},'travel'),
 ('Start a weekly summary for newly created Project CYGNUS.',{'project':'CYGNUS'},'research'),
 ('Please check an untracked application APP-800 to Aurora Systems.',{'application_id':'APP-800'},'email'),
 ('Help me schedule a dentist appointment with a new clinic.',{},'calendar'),
 ('Prepare a project charter for a new home energy audit.',{},'research'),
]
for i,(q,ents,typ) in enumerate(novel):
 add(q,'CREATE',None,'unspecified',ents,typ,'novel_actionable_task',
    'Actionable user request with no corresponding internal workflow.', 'medium')
assert len(actions)==155
# CLARIFY: genuine internal ambiguity / under-specification; 20 items
ambiguity=[
 ('Can you follow up on Alice auto insurance quote?',{'contact':'Alice'},'email'),
 ('What happened with Carol job offer?',{'contact':'Carol'},'email'),
 ('Check David invoice and tell me if it was paid.',{'contact':'David'},'email'),
 ('Which Emily flight did we set up the monitor for?',{'contact':'Emily'},'research'),
 ('Continue the ATLAS issue I mentioned.',{'project':'ATLAS'},'coding'),
 ('Please update the NOVA or COMET report we discussed.',{},'research'),
 ('Did Henry support get back to us?',{'contact':'Henry'},'support'),
 ('Do we have a response on Ivy order?',{'contact':'Ivy'},'research'),
 ('Move Jack meeting to Friday.',{'contact':'Jack'},'calendar'),
 ('Please revisit Kate finance file.',{'contact':'Kate'},'research'),
 ('Any news from Liam repair technician?',{'contact':'Liam'},'support'),
 ('Did Maya event receive approval?',{'contact':'Maya'},'calendar'),
 ('Check how Nora astrophotography edit is progressing.',{'contact':'Nora'},'research'),
 ('Any response on Oliver job application?',{'contact':'Oliver'},'email'),
 ('Is the Patricia supplier agreement signed?',{'contact':'Patricia'},'email'),
 ('Please revisit Quinn marketing project.',{'contact':'Quinn'},'research'),
 ('Have we finalized Rachel workshop?',{'contact':'Rachel'},'calendar'),
 ('Check which of Grace itineraries is confirmed.',{'contact':'Grace'},'travel'),
 ('Could you continue Bob insurance work?',{'contact':'Bob'},'email'),
 ('Go back to Alice case from earlier.',{'contact':'Alice'},None),
]
for q,hints,typ in ambiguity:
 add(q,'CLARIFY',None,'continue',hints,typ,'ambiguous_existing_workflows',
    'Multiple plausible existing internal workflow identities; a unique target is not established.', 'hard')
assert len(actions)==175
# CLARIFY: multi-object in one request under CURRENT single-workflow action schema; 13 items
multi=[
 ('Check Alice quote AUTO-101 and her separate HOME-102 renewal.',{'contact':'Alice'},'email'),
 ('Review Carol Pine offer OFFER-301 and Cedar offer OFFER-302.',{'contact':'Carol'},'email'),
 ('Check both David invoices INV-404 and INV-405.',{'contact':'David'},'email'),
 ('Monitor Emily flights AC123 and WS456.',{'contact':'Emily'},'research'),
 ('Update the NOVA digest and the COMET risk report.',{},'research'),
 ('Continue ATLAS backend ISSUE-426 and mobile ISSUE-427.',{'project':'ATLAS'},'coding'),
 ('Reply about Henry printer TCK-301 and VPN TCK-302.',{'contact':'Henry'},'support'),
 ('Follow Grace Paris TRIP-501 and Tokyo TRIP-502 arrangements.',{'contact':'Grace'},'travel'),
 ('Check both Ivy orders ORD-831 and ORD-832.',{'contact':'Ivy'},'research'),
 ('Schedule Jack supervisor meeting MTG-702 and review THESIS-701.',{'contact':'Jack'},None),
 ('Track Liam furnace JOB-901 and window JOB-902.',{'contact':'Liam'},'support'),
 ('Update Maya conference EVT-110 plus the webinar EVT-111.',{'contact':'Maya'},'calendar'),
 ('Continue Oliver backend JOB-210 and AI JOB-211 applications.',{'contact':'Oliver'},'email'),
]
for q,hints,typ in multi:
 add(q,'CLARIFY',None,'continue',hints,typ,'multiple_internal_targets',
    'More than one distinct internal workflow is required, but current routing schema supports one target.', 'hard')
assert len(actions)==188
# CLARIFY: insufficient task identity or deliberate reference to absent INTERNAL OpenPoke workflow (not an external object).
insufficient=[
 'Pick up where we left off.',
 'Can you sort that out?',
 'Please continue the second one.',
 'What was the status of that thing yesterday?',
 'Tell me what to do next with it.',
 'Could you deal with the unresolved item?',
 'Finish the task I was thinking about.',
]
for q in insufficient:
 add(q,'CLARIFY',None,'continue',{},None,'missing_task_identity',
     'No identifiable user goal or internal workflow target is present in the request alone.', 'hard')
assert len(actions)==195
internal_absent=[
 'Resume my exact OpenPoke workflow with ID 00000000-0000-4000-8000-000000009911; do not create a new one.',
 'Open the existing OpenPoke workflow named MY-PRIVATE-UNKNOWN; I only want to resume that record.',
 'Continue the internal workflow that I deleted yesterday; I do not want a replacement task.',
 'Use the OpenPoke workflow with key NONEXISTENT-472, not a newly created workflow.',
 'Please reopen my archived OpenPoke task UUID 00000000-0000-4000-8000-000000009912 as the same workflow.',
]
for q in internal_absent:
 add(q,'CLARIFY',None,'continue',{},None,'explicit_missing_internal_workflow',
     'The user specifically requires an existing internal workflow that is not available; silently creating a different workflow would violate the request.', 'hard')
assert len(actions)==200
# Check unique queries, keys, refs, target resolution.
assert len(set(w['key'] for w in workflows))==200
assert len(set(c['query'].lower().strip() for c in actions))==200
wkeys={w['key'] for w in workflows}
assert all(c['target_key'] in wkeys for c in actions if c['expected_action']=='RESUME')
assert all(c['target_key'] is None for c in actions if c['expected_action']!='RESUME')
# Deterministic development/holdout split. Group RESUME by target workflow ID:
# no RESUME paraphrase for the same workflow appears in both partitions.
by_action=collections.defaultdict(list)
for i,c in enumerate(actions):by_action[c['expected_action']].append(i)
target_keys=sorted({c['target_key'] for c in actions if c['expected_action']=='RESUME'})
random.Random(20261028).shuffle(target_keys)
dev_targets=set(target_keys[:8])
resume_dev=[i for i,c in enumerate(actions) if c['expected_action']=='RESUME' and c['target_key'] in dev_targets]
assert len(resume_dev)==16
random.Random(20261029).shuffle(by_action['CREATE'])
random.Random(20261030).shuffle(by_action['CLARIFY'])
selected=set(resume_dev+by_action['CREATE'][:14]+by_action['CLARIFY'][:10])
assert len(selected)==40
for i,c in enumerate(actions):
 c['split']='dev' if i in selected else 'holdout'

metadata={
 'dataset_version':'v2.0',
 'description':('Independent synthetic benchmark for OpenPoke workflow-relative routing; '
                '200 stored internal workflows + 200 labeled user requests. '
                'Generated and reviewed for schema/consistency, but not independently human-blind-labeled.'),
 'label_policy':{
  'scope':'OpenPoke internal workflow identity, not existence or lifecycle of external cases/emails/documents',
  'RESUME':'Continue exactly one identifiable stored internal workflow that covers all requested tasks.',
  'CREATE':'Actionable task with no corresponding stored internal workflow, including references to externally existing objects, or a distinct new task scope.',
  'CLARIFY':'Insufficient task identity, multiple plausible existing workflows, multiple independent workflows beyond current single-route contract, or user explicitly requires an unavailable internal workflow.',
  'intent_field':'Linguistic/request-level intent hint; continue may refer to an external task, and does not imply an existing internal OpenPoke workflow.',
  'task_type_hint':'Oracle hint extracted from the user request where identifiable; not intended as a prediction label.',
 },
 'generation':{
  'workflows_curated':42,'workflows_deterministic_distractors':158,
  'cases_individually_authored':200,'split_policy':'40 dev / 160 holdout; RESUME cases grouped by target workflow, deterministic seed',
  'privacy':'Entirely fictional; no actual user emails or account data',
  'limits':['One workflow per routing decision; multi-target requests marked CLARIFY until multi-route supported',
           'All workflows active and belong to one evaluation user; no archived-state cases',
           'Synthetic test; not representative production traffic; label disputes need manual review',
           'Changing action labels changes semantics; do not compare v1 accuracy with v2 without re-running both baselines'],
 },
}
full=dict(metadata,workflows=workflows,cases=actions)
(OUT/'workflow_routing_v2_200.json').write_text(json.dumps(full,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for split in ['dev','holdout']:
 obj=dict(metadata,description=f'Workflow routing v2.0 {split} split; full common corpus, cases filtered for {split}.',workflows=workflows,cases=[c for c in actions if c['split']==split])
 (OUT/f'workflow_routing_v2_{split}.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('counts',collections.Counter(c['expected_action'] for c in actions),collections.Counter(c['group'] for c in actions),collections.Counter(c['split'] for c in actions))
print('files',[(p.name,p.stat().st_size) for p in OUT.iterdir()])
