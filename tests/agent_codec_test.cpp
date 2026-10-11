#undef NDEBUG
#include "agent_client/decision_codec.h"
#include "agent_client/game_event_codec.h"
#include "ocgcore/common.h"
#include <cassert>
#include <iostream>
#include <string>
using namespace ygo::agent_client;
using J = nlohmann::json;
using B = std::vector<std::uint8_t>;
void u32(B& b, unsigned n) { for(int i=0;i<4;++i)b.push_back(n>>(8*i)); }
void card(B& b, unsigned code, bool extra=false, unsigned param=0) {u32(b,code); b.insert(b.end(),{0,4,0}); if(extra)b.push_back(param);}
void game_events() {
 auto parse=[](const B& bytes,bool first=true,bool grave=true,bool reversed=false) {
   return ParseGameEvent(bytes.data(),bytes.size(),first,grave,reversed);
 };
 assert(GameEventMessage(MSG_TOSS_COIN) && GameEventMessage(MSG_RANDOM_SELECTED) &&
   GameEventMessage(MSG_SHUFFLE_SET_CARD) && GameEventMessage(MSG_EQUIP));
 assert(!GameEventMessage(MSG_NEW_TURN));
 assert((*parse(B{MSG_TOSS_COIN,1,1,0}))["kind"]=="coin_tossed");
 assert((*parse(B{MSG_RANDOM_SELECTED,1,1,0,LOCATION_MZONE,2,0}))["kind"]==
   "cards_randomly_selected");
 B reveal={MSG_CONFIRM_DECKTOP,1,2};
 u32(reveal,123);reveal.insert(reveal.end(),{1,LOCATION_DECK,7});
 u32(reveal,456);reveal.insert(reveal.end(),{1,LOCATION_DECK,6});
 auto shown=parse(reveal);assert(shown && (*shown)["kind"]=="deck_cards_revealed" &&
   (*shown)["cards"]==J::array({J{{"player",1},{"location",LOCATION_DECK},{"card_id",123}},
                                J{{"player",1},{"location",LOCATION_DECK},{"card_id",456}}}));
 assert((*parse(reveal,false))["player"]==0);
 B extra=reveal;extra[0]=MSG_CONFIRM_EXTRATOP;extra[8]=LOCATION_EXTRA;extra[15]=LOCATION_EXTRA;
 assert((*parse(extra))["zone"]=="extra");
 B deck_top={MSG_DECK_TOP,1,2};u32(deck_top,0x80000000U|123U);
 assert((*parse(deck_top))["card_id"]==123 && (*parse(deck_top))["card_reversed"]==true &&
   (*parse(deck_top))["top_offset"]==2);
 assert((*parse(B{MSG_REVERSE_DECK},true,true,true))["deck_reversed"]==true);
 assert((*parse(B{MSG_SWAP_GRAVE_DECK,1}))["kind"]=="grave_deck_swapped");
 B swapped={MSG_SWAP};u32(swapped,123);swapped.insert(swapped.end(),{0,LOCATION_MZONE,2,POS_FACEDOWN_DEFENSE});
 u32(swapped,456);swapped.insert(swapped.end(),{1,LOCATION_SZONE,3,POS_FACEDOWN_DEFENSE});
 auto swap_event=parse(swapped);assert(swap_event && (*swap_event)["cards"].size()==2 &&
   !(*swap_event).contains("card_id") && !(*swap_event)["cards"][0].contains("card_id"));
 B disabled={MSG_FIELD_DISABLED};u32(disabled,0x12345678);
 assert((*parse(disabled))["value"]==0x12345678);
 assert((*parse(disabled,false))["value"]==0x56781234);
 for(auto type:{MSG_EQUIP,MSG_CARD_TARGET,MSG_CANCEL_TARGET}) {
   B relation={static_cast<std::uint8_t>(type),0,LOCATION_SZONE,2,0,1,LOCATION_MZONE,3,0};
   auto event=parse(relation);assert(event && (*event)["cards"].size()==2);
   assert((*event)["cards"][0]["sequence"]==2 && (*event)["cards"][1]["sequence"]==3);
   relation[6]=LOCATION_HAND;
   auto private_relation=parse(relation);assert(private_relation &&
     !(*private_relation)["cards"][1].contains("sequence"));
 }
 for(auto type:{MSG_ADD_COUNTER,MSG_REMOVE_COUNTER}) {
   B counter_event={static_cast<std::uint8_t>(type),0x34,0x12,1,LOCATION_MZONE,2,3,0};
   auto event=parse(counter_event);assert(event && (*event)["counter_type"]==0x1234 &&
     (*event)["count"]==3 && (*event)["cards"][0]["sequence"]==2);
 }
 B missed={MSG_MISSED_EFFECT,1,LOCATION_HAND,7,0};u32(missed,98765432);
 auto missed_event=parse(missed);assert(missed_event &&
   (*missed_event)["kind"]=="effect_timing_missed" &&
   !(*missed_event)["cards"][0].contains("sequence") &&
   (*missed_event)["card_id"]==98765432);
 B hands={MSG_HAND_RES,static_cast<std::uint8_t>(1|(3<<2))};
 assert((*parse(hands))["self_choice"]=="rock" &&
   (*parse(hands,false))["self_choice"]=="scissors");
 for(const B& packet:{reveal,extra,deck_top,B{MSG_REVERSE_DECK},B{MSG_SWAP_GRAVE_DECK,1},
   swapped,disabled,B{MSG_EQUIP,0,8,0,0,1,4,0,0},
   B{MSG_CARD_TARGET,0,8,0,0,1,4,0,0},B{MSG_CANCEL_TARGET,0,8,0,0,1,4,0,0},
   B{MSG_ADD_COUNTER,1,0,0,4,0,1,0},B{MSG_REMOVE_COUNTER,1,0,0,4,0,1,0},missed,hands}) {
   assert(parse(packet));
   for(std::size_t length=0;length<packet.size();++length)
     assert(!ParseGameEvent(packet.data(),length,true,true,false));
   auto trailing=packet;trailing.push_back(0);assert(!parse(trailing));
 }
 assert(!parse(B{MSG_HAND_RES,0}));
 assert(!parse(B{MSG_DECK_TOP,2,0,1,0,0,0}));
}
ParseDecisionResult p(const B& b) { auto x=ParseDecision(b.data(),b.size()); if(!x.decision)std::cerr<<x.error.message<<"\n"; assert(x.decision); return x; }
B response(const B& b, const J& a) {auto x=p(b); auto e=EncodeDecision(*x.decision,a); if(!e.response)std::cerr<<e.error.message<<"\n"; assert(e.response);return e.response->payload;}
J choice(const char* c) {return {{"kind","choice"},{"candidate_id",c}};}
J select(std::initializer_list<const char*> cs) { J a={{"kind","select_cards"},{"candidate_ids",J::array()}};for(auto c:cs)a["candidate_ids"].push_back(c);return a; }
void reject(const B& b,const J& a) {assert(!EncodeDecision(*p(b).decision,a).response);}
void roundtrip(const B &b, const J &action) {
  auto prompt = p(b).decision;
  auto encoded = EncodeDecision(*prompt, action);
  assert(encoded.response);
  auto decoded = DecodeDecisionResponse(*prompt, encoded.response->packet_type,
                                        encoded.response->payload.data(),
                                        encoded.response->payload.size());
  if (!decoded.action)
    std::cerr << decoded.error.code << ": " << decoded.error.message << "\n";
  assert(decoded.action && *decoded.action == action);
}
int main(int argc, char** argv){
 game_events();
 auto hand=ParseDecision(nullptr,0,DecisionSource::select_hand);assert(hand.decision);auto e=EncodeDecision(*hand.decision,choice("c0"));assert(e.response->packet_type==3&&e.response->payload==B{2});
 auto tp=ParseDecision(nullptr,0,DecisionSource::select_turn_player);assert(tp.decision);assert(EncodeDecision(*tp.decision,choice("c0")).response->payload==B{1});
 B yes={MSG_SELECT_YESNO,0};u32(yes,123);assert(response(yes,choice("c0"))==B({1,0,0,0}));reject(yes,{{"kind","choice"},{"candidate_id","c0"},{"response",1}});
 B effect={MSG_SELECT_EFFECTYN,0};card(effect,123,true);u32(effect,99);assert(response(effect,choice("c1"))==B({0,0,0,0}));
 B option={MSG_SELECT_OPTION,0,2};u32(option,99);u32(option,88);assert(response(option,choice("c1"))==B({1,0,0,0}));
 auto named_option=ParseDecision(option.data(),option.size(),DecisionSource::game_message,nullptr,
   [](std::uint32_t id) { return id==99 ? std::string("加入手卡") : std::string("特殊召唤"); });
 assert(named_option.decision && named_option.decision->prompt()["candidates"][0]["description"]=="加入手卡" &&
   named_option.decision->prompt()["candidates"][1]["description"]=="特殊召唤" &&
   named_option.decision->prompt()["candidates"][0]["description_id"]==99 &&
   EncodeDecision(*named_option.decision,choice("c1")).response->payload==B({1,0,0,0}));
 B idle={MSG_SELECT_IDLECMD,0,2};card(idle,2);card(idle,1);idle.insert(idle.end(),{0,0,0,0,0,1,0,1});assert(response(idle,choice("c1"))==B({0,0,1,0}));assert(response(idle,choice("c2"))==B({6,0,0,0}));
 B battle={MSG_SELECT_BATTLECMD,1,0,1};card(battle,2);battle.insert(battle.end(),{1,0,1});assert(response(battle,choice("c0"))==B({1,0,0,0}));
 B cards={MSG_SELECT_CARD,0,1,1,2,2};card(cards,2,true);card(cards,1,true);assert(response(cards,select({"c1","c0"}))==B({2,1,0}));reject(cards,select({"c0","c0"}));reject(cards,select({}));assert(response(cards,choice("c2"))==B({255,255,255,255}));
 B cards_cancel_two=cards;cards_cancel_two[2]=2;assert(response(cards_cancel_two,choice("c2"))==B({255,255,255,255}));
 B step={MSG_SELECT_UNSELECT_CARD,0,1,0,1,2,1};card(step,2,true);step.push_back(1);card(step,1,true);assert(response(step,{{"kind","select_step"},{"candidate_id","c1"}})==B({1,1}));assert(response(step,{{"kind","select_step"},{"candidate_id","c2"}})==B({255,255,255,255}));
 B chain={MSG_SELECT_CHAIN,0,1,0};u32(chain,0);u32(chain,0);chain.insert(chain.end(),{0,1});card(chain,2,true);u32(chain,77);assert(response(chain,choice("c0"))==B({0,0,0,0}));reject(chain,choice("c1"));
 B position={MSG_SELECT_POSITION,0};u32(position,22);position.push_back(5);assert(response(position,choice("c1"))==B({4,0,0,0}));
 B tribute={MSG_SELECT_TRIBUTE,0,0,2,2,2};card(tribute,2,true,2);card(tribute,1,true,1);assert(response(tribute,select({"c0"}))==B({1,0}));reject(tribute,select({"c1"}));
 B counter={MSG_SELECT_COUNTER,0,1,0,3,0,2};card(counter,2);counter.insert(counter.end(),{2,0});card(counter,1);counter.insert(counter.end(),{3,0});J allocations={{"kind","distribute_counters"},{"allocations",J::array({J{{"candidate_id","c1"},{"count",3}}})}};assert(response(counter,allocations)==B({0,0,3,0}));allocations["allocations"][0]["count"]=4;reject(counter,allocations);
 B sum={MSG_SELECT_SUM,0,0};u32(sum,7);sum.insert(sum.end(),{1,2,1});card(sum,10);u32(sum,2);sum.push_back(2);card(sum,20);u32(sum,5|(3<<16));card(sum,30);u32(sum,4);assert(response(sum,select({"c0","c1"}))==B({2,0,0}));reject(sum,select({"c0","c1","c2"})); B sum9=sum; sum9[3]=9; assert(response(sum9,select({"c0","c1","c2"}))==B({3,0,0,1}));reject(sum,select({"c1"}));reject(sum,select({"c0","c2"}));
 B atleast=sum;atleast[1]=1;assert(response(atleast,select({"c0","c1"}))==B({2,0,0}));reject(atleast,select({"c0","c1","c2"}));
 B sort={MSG_SORT_CARD,0,3};card(sort,3);card(sort,2);card(sort,1);assert(response(sort,select({"c2","c0","c1"}))==B({1,2,0}));reject(sort,select({"c1","c0"}));
 B place={MSG_SELECT_PLACE,1,1};u32(place,~(1U|(1U<<16)));J places={{"kind","select_places"},{"places",J::array({J{{"controller",0},{"location","monster"},{"sequence",0}}})}};assert(response(place,places)==B({0,4,0}));places["places"][0]["sequence"]=1;reject(place,places);
 B race={MSG_ANNOUNCE_RACE,0,2};u32(race,3);assert(response(race,select({"c0","c1"}))==B({3,0,0,0}));reject(race,select({"c0"}));
 B attr={MSG_ANNOUNCE_ATTRIB,0,1};u32(attr,5);assert(response(attr,select({"c1"}))==B({4,0,0,0}));
 B number={MSG_ANNOUNCE_NUMBER,0,2};u32(number,10);u32(number,20);assert(response(number,choice("c1"))==B({1,0,0,0}));
 B rps={MSG_ROCK_PAPER_SCISSORS,1};assert(response(rps,choice("c2"))==B({3,0,0,0}));
 for(const auto& b:{yes,effect,option,idle,battle,cards,step,chain,position,tribute,counter,sum,atleast,sort,place,race,attr,number,rps}) {for(std::size_t len=0;len<b.size();++len)assert(!ParseDecision(b.data(),len).decision);auto trailing=b;trailing.push_back(0);assert(!ParseDecision(trailing.data(),trailing.size()).decision);}
 B announce={MSG_ANNOUNCE_CARD,0,1};u32(announce,0);auto unsupported=ParseDecision(announce.data(),announce.size());assert(!unsupported.decision&&unsupported.error.code=="unsupported_prompt");
 std::vector<std::uint32_t> allowed{12345678,87654321,12345678};
 auto announcement=ParseDecision(announce.data(),announce.size(),DecisionSource::game_message,&allowed);assert(announcement.decision);
 assert(announcement.decision->prompt()["kind"]=="announce_card");assert(announcement.decision->prompt()["constraints"]["allowed_card_ids"].size()==2);
 auto valid_announce=EncodeDecision(*announcement.decision,{{"kind","announce_card"},{"card_id",12345678}});assert(valid_announce.response&&valid_announce.response->packet_type==1&&valid_announce.response->payload==B({78,97,188,0}));
 allowed.assign({42});assert(EncodeDecision(*announcement.decision,{{"kind","announce_card"},{"card_id",87654321}}).response);
 for(const J& code:{J(42),J(0),J(-1),J(true),J(1.5),J("12345678"),J(4294967296ULL)})assert(!EncodeDecision(*announcement.decision,{{"kind","announce_card"},{"card_id",code}}).response);
 assert(!EncodeDecision(*announcement.decision,choice("c0")).response);
 assert(!EncodeDecision(*announcement.decision,{{"kind","announce_card"},{"card_id",12345678},{"bytes",J::array({1})}}).response);
 std::vector<std::uint32_t> empty;assert(!ParseDecision(announce.data(),announce.size(),DecisionSource::game_message,&empty).decision);
 allowed.assign({0});assert(!ParseDecision(announce.data(),announce.size(),DecisionSource::game_message,&allowed).decision);
 allowed.assign({12345678});for(std::size_t len=0;len<announce.size();++len)assert(!ParseDecision(announce.data(),len,DecisionSource::game_message,&allowed).decision);
 for (const auto &item : std::vector<std::pair<B, J>>{
          {yes, choice("c0")},
          {effect, choice("c1")},
          {option, choice("c1")},
          {idle, choice("c1")},
          {battle, choice("c0")},
          {cards, select({"c1", "c0"})},
          {step, J{{"kind", "select_step"}, {"candidate_id", "c1"}}},
          {chain, choice("c0")},
          {position, choice("c1")},
          {tribute, select({"c0"})},
          {counter, J{{"kind", "distribute_counters"},
                      {"allocations",
                       J::array({J{{"candidate_id", "c1"}, {"count", 3}}})}}},
          {sum, select({"c0", "c1"})},
          {sort, select({"c2", "c0", "c1"})},
          {place, J{{"kind", "select_places"},
                    {"places", J::array({J{{"controller", 0},
                                           {"location", "monster"},
                                           {"sequence", 0}}})}}},
          {race, select({"c0", "c1"})},
          {attr, select({"c1"})},
          {number, choice("c1")},
          {rps, choice("c2")}})
   roundtrip(item.first, item.second);
 auto announced = DecodeDecisionResponse(
     *announcement.decision, 1, valid_announce.response->payload.data(), 4);
 assert(announced.action && *announced.action == J({{"kind", "announce_card"},
                                                    {"card_id", 12345678}}));
 B wrong = {9, 0, 0, 0};
 assert(!DecodeDecisionResponse(*p(yes).decision, 1, wrong.data(), wrong.size())
             .action);
 assert(!DecodeDecisionResponse(*p(yes).decision, 2, B{1}.data(), 1).action);
 B ambiguous_step = step;
 ambiguous_step[3] = 1;
 auto step_ambiguous = DecodeDecisionResponse(*p(ambiguous_step).decision, 1,
                                              B{255, 255, 255, 255}.data(), 4);
 assert(!step_ambiguous.action &&
        step_ambiguous.error.code == "ambiguous_response");
 B two_mandatory={MSG_SELECT_SUM,0,0};u32(two_mandatory,7);two_mandatory.insert(two_mandatory.end(),{1,1,2});
 card(two_mandatory,10);u32(two_mandatory,2);card(two_mandatory,11);u32(two_mandatory,1);
 two_mandatory.push_back(2);card(two_mandatory,20);u32(two_mandatory,4);card(two_mandatory,21);u32(two_mandatory,5);
 roundtrip(two_mandatory,select({"c0","c1","c2"}));
 B bad_placeholder={3,0,1,0};assert(!DecodeDecisionResponse(*p(two_mandatory).decision,1,bad_placeholder.data(),bad_placeholder.size()).action);
 B optional_place={MSG_SELECT_PLACE,1,0};u32(optional_place,UINT32_MAX);
 J skip_place={{"kind","select_places"},{"places",J::array()}};
 assert(response(optional_place,skip_place)==B({1,0,0}));roundtrip(optional_place,skip_place);
 auto hand_decoded = DecodeDecisionResponse(
     *hand.decision, e.response->packet_type, e.response->payload.data(), 1);
 assert(hand_decoded.action && *hand_decoded.action == choice("c0"));
 assert(std::string(CoinFaceForSelectedOption(60)) == "heads");
 assert(std::string(CoinFaceForSelectedOption(61)) == "tails");
 assert(CoinFaceForSelectedOption(62) == nullptr);
 B observed_coin = {MSG_TOSS_COIN, 1, 1, 0};
 auto coin_event =
     ParseRandomResultEvent(observed_coin.data(), observed_coin.size(), 1);
 assert(coin_event && *coin_event == J({{"kind", "coin_tossed"},
                                        {"player", 1},
                                        {"count", 1},
                                        {"results", J::array({"tails"})}}));
 B observed_dice = {MSG_TOSS_DICE, 0, 3, 1, 6, 2};
 auto dice_event =
     ParseRandomResultEvent(observed_dice.data(), observed_dice.size(), 0);
 assert(dice_event && *dice_event == J({{"kind", "dice_rolled"},
                                        {"player", 0},
                                        {"count", 3},
                                        {"results", J::array({1, 6, 2})}}));
 for (const auto &packet : {observed_coin, observed_dice}) {
   for (std::size_t length = 0; length < packet.size(); ++length)
     assert(!ParseRandomResultEvent(packet.data(), length, 0));
   auto extra = packet;
   extra.push_back(0);
   assert(!ParseRandomResultEvent(extra.data(), extra.size(), 0));
 }
 for (const B &invalid :
      {B{MSG_TOSS_COIN, 2, 1, 0}, B{MSG_TOSS_COIN, 1, 0},
       B{MSG_TOSS_COIN, 1, 1, 2}, B{MSG_TOSS_DICE, 0, 1, 0},
       B{MSG_TOSS_DICE, 0, 1, 7}, B{MSG_TOSS_DICE, 0, 6, 1, 2, 3, 4, 5, 6}})
   assert(!ParseRandomResultEvent(invalid.data(), invalid.size(), 0));
 assert(
     !ParseRandomResultEvent(observed_coin.data(), observed_coin.size(), -1));
 B selected = {MSG_RANDOM_SELECTED, 1, 3,
               1, LOCATION_HAND, 4, 0,
               0, LOCATION_MZONE, 2, 0,
               1, LOCATION_DECK, 9, 0};
 const auto selected_first = ParseRandomSelectionEvent(
     selected.data(), selected.size(), true, true);
 assert(selected_first && *selected_first ==
     J({{"kind", "cards_randomly_selected"}, {"player", 1}, {"count", 3},
        {"cards", J::array({J{{"player", 1}, {"location", LOCATION_HAND}},
                             J{{"player", 0}, {"location", LOCATION_MZONE}, {"sequence", 2}},
                             J{{"player", 1}, {"location", LOCATION_DECK}}})}}));
 const auto selected_second = ParseRandomSelectionEvent(
     selected.data(), selected.size(), false, true);
 assert(selected_second && (*selected_second)["player"] == 0);
 assert((*selected_second)["cards"][0] ==
        J({{"player", 0}, {"location", LOCATION_HAND}, {"sequence", 4}}));
 assert((*selected_second)["cards"][2] ==
        J({{"player", 0}, {"location", LOCATION_DECK}}));
 B selected_hidden = {MSG_RANDOM_SELECTED, 0, 2,
                      1, LOCATION_EXTRA, 3, 0,
                      0, LOCATION_GRAVE, 4, 0};
 const auto hidden_event = ParseRandomSelectionEvent(
     selected_hidden.data(), selected_hidden.size(), true, false);
 assert(hidden_event && (*hidden_event)["cards"] ==
     J::array({J{{"player", 1}, {"location", LOCATION_EXTRA}},
               J{{"player", 0}, {"location", LOCATION_GRAVE}}}));
 B many_selected = {MSG_RANDOM_SELECTED, 0, 255};
 for (int i = 0; i < 255; ++i)
   many_selected.insert(many_selected.end(), {0, LOCATION_MZONE, 0, 0});
 const auto many_event = ParseRandomSelectionEvent(
     many_selected.data(), many_selected.size(), true, true);
 assert(many_event && (*many_event)["count"] == 255 &&
        (*many_event)["cards"].size() == 255);
 for (std::size_t length = 0; length < selected.size(); ++length)
   assert(!ParseRandomSelectionEvent(selected.data(), length, true, true));
 B extra_selected = selected;
 extra_selected.push_back(0);
 assert(!ParseRandomSelectionEvent(extra_selected.data(), extra_selected.size(), true, true));
 for (const B &invalid :
      {B{MSG_RANDOM_SELECTED, 2, 1, 0, LOCATION_MZONE, 0, 0},
       B{MSG_RANDOM_SELECTED, 0, 0},
       B{MSG_RANDOM_SELECTED, 0, 1, 2, LOCATION_HAND, 0, 0},
       B{MSG_RANDOM_SELECTED, 0, 1, 0, 0, 0, 0}})
   assert(!ParseRandomSelectionEvent(invalid.data(), invalid.size(), true, true));
 B set_shuffle = {MSG_SHUFFLE_SET_CARD, LOCATION_MZONE, 3,
                  0, LOCATION_MZONE, 3, 8,
                  0, LOCATION_MZONE, 2, 8,
                  0, LOCATION_MZONE, 0, 8};
 set_shuffle.insert(set_shuffle.end(), 12, 0);
 const auto shuffled_first = ParseSetShuffleEvent(
     set_shuffle.data(), set_shuffle.size(), true);
 assert(shuffled_first && *shuffled_first ==
     J({{"kind", "set_cards_shuffled"}, {"player", 0},
        {"zone", "monster"}, {"count", 3}}));
 assert(ParseGameEvent(set_shuffle.data(), set_shuffle.size(), true, true, false)==shuffled_first);
 const auto shuffled_second = ParseSetShuffleEvent(
     set_shuffle.data(), set_shuffle.size(), false);
 assert(shuffled_second && (*shuffled_second)["player"] == 1);
 for(std::size_t length = 0; length < set_shuffle.size(); ++length)
   assert(!ParseSetShuffleEvent(set_shuffle.data(), length, true));
 B extra_shuffle = set_shuffle;
 extra_shuffle.push_back(0);
 assert(!ParseSetShuffleEvent(extra_shuffle.data(), extra_shuffle.size(), true));
 B mixed_shuffle = set_shuffle;
 mixed_shuffle[7] = 1;
 assert(!ParseSetShuffleEvent(mixed_shuffle.data(), mixed_shuffle.size(), true));
 if (argc == 2 && std::string(argv[1]) == "--dump-prompts") {
   J prompts = J::array({hand.decision->prompt(), tp.decision->prompt(),
                         announcement.decision->prompt()});
   for (const auto &message :
        {yes, effect, option, idle, battle, cards, step, chain, position,
         tribute, counter, sum, atleast, sort, place, race, attr, number, rps})
     prompts.push_back(p(message).decision->prompt());
   std::cout << prompts.dump() << '\n';
 } else
   std::cout << "20 protocol families, pre-duel sources, invalid actions and "
                "every truncation passed\n";
}
