# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#*** nmeta - Network Metadata - Policy Interpretation Class and Methods

"""
This module is part of the nmeta suite running on top of Ryu SDN controller
to provide network identity and flow (Traffic Classification - TC) metadata.
It expects a file called "tc_policy.yaml" to be in the config subdirectory
containing properly formed YAML that conforms the the particular specifications
that this program expects. See constant tuples at start of program for valid
attributes to use.
"""

import logging
import logging.handlers

import sys
import os

#*** Packet-related imports:
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp

#*** nmeta imports:
import tc_static
import tc_identity
import tc_statistical
import tc_payload

#*** YAML for config and policy file parsing:
import yaml

#*** Describe supported syntax in tc_policy.yaml so that it can be tested
#*** for validity. Here are valid policy rule attributes:
TC_CONFIG_POLICYRULE_ATTRIBUTES = ('comment', 'conditions', 'actions')
#*** Dictionary of valid conditions stanza attributes with type:
TC_CONFIG_CONDITIONS = {'eth_src': 'MACAddress',
                               'eth_dst': 'MACAddress', 
                               'ip_src': 'IPAddressSpace', 
                               'ip_dst': 'IPAddressSpace',
                               'tcp_src': 'PortNumber', 
                               'tcp_dst': 'PortNumber', 
                               'eth_type': 'EtherType',
                               'identity_lldp_systemname': 'String',
                               'identity_lldp_systemname_re': 'String',
                               'payload_type': 'String',
                               'statistical_qos_bandwidth_1': 'String',
                               'match_type': 'MatchType',
                               'conditions': 'PolicyConditions'}
TC_CONFIG_ACTIONS = ('set_qos_tag', 'set_desc_tag', 'pass_return_tags')
TC_CONFIG_MATCH_TYPES = ('any', 'all', 'statistical')

class TrafficClassificationPolicy(object):
    """
    This class is instantiated by nmeta.py and provides methods
    to ingest the policy file tc_policy.yaml and check flows
    against policy to see if actions exist
    """
    def __init__(self, tc_policy_logging_level, tc_static_logging_level,
                   tc_identity_logging_level, tc_payload_logging_level,
                   tc_statistical_logging_level):
        #*** Set up logging to write to syslog:
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(tc_policy_logging_level)
        #*** Log to syslog on localhost
        self.handler = logging.handlers.SysLogHandler(address=('localhost',
                                                      514), facility=19)
        formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
        self.handler.setFormatter(formatter)
        self.logger.addHandler(self.handler)
        #*** Name of the config file:
        self.policy_filename = "tc_policy.yaml"
        self.config_directory = "config"
        #*** Get working directory:
        self.working_directory = os.path.dirname(__file__)
        #*** Build the full path and filename for the config file:
        self.fullpathname = os.path.join(self.working_directory,
                                         self.config_directory,
                                         self.policy_filename)
        self.logger.info("INFO:  module=tc_policy About to open config file "
                         "%s", self.fullpathname)
        #*** Ingest the policy file:
        try:
            with open(self.fullpathname, 'r') as filename:
                self._tc_policy = yaml.load(filename)
        except (IOError, OSError) as exception:
            self.logger.error("ERROR: module=tc_policy Failed to open policy "
                              "file %s %s", self.fullpathname, exception)
            sys.exit("Exiting nmeta. Please create traffic classification "
                             "policy file")
        #*** Instantiate Classes:
        self.static = tc_static.StaticInspect(tc_static_logging_level)
        self.identity = tc_identity.IdentityInspect(tc_identity_logging_level)
        self.payload = tc_payload.PayloadInspect(tc_payload_logging_level)
        self.statistical = tc_statistical.StatisticalInspect \
                                (tc_statistical_logging_level)
        #*** Run a test on the ingested traffic classification policy to ensure
        #*** that it is good:
        self.validate_policy()

    def validate_policy(self):
        """
        Check Traffic Classification (TC) policy to ensure that it is in
        correct format so that it won't cause unexpected errors during
        packet checks.
        """
        self.logger.debug("DEBUG: module=tc_policy Validating TC Policy...")
        for policy_rule in self._tc_policy.keys():
            self.logger.debug("DEBUG: module=tc_policy Validating PolicyRule "
                              "%s %s", policy_rule, 
                              self._tc_policy[policy_rule])
            #*** Test for unsupported PolicyRule attributes:
            for policy_rule_parameter in self._tc_policy[policy_rule].keys():
                if not policy_rule_parameter in \
                        TC_CONFIG_POLICYRULE_ATTRIBUTES:
                    self.logger.critical("CRITICAL: module=tc_policy The "
                                         "following PolicyRule attribute is "
                                         "invalid: %s ", policy_rule_parameter)
                    sys.exit("Exiting nmeta. Please fix error in "
                             "tc_policy.yaml file")
                if policy_rule_parameter == 'conditions':
                    #*** Call function to validate the policy condition and
                    #*** any nested policy conditions that it may contain:
                    self._validate_conditions(
                                    self._tc_policy[policy_rule]
                                    [policy_rule_parameter])
                if policy_rule_parameter == 'actions':
                    #*** Check actions are valid:
                    for action in self._tc_policy[policy_rule] \
                                  [policy_rule_parameter].keys():
                        if not action in TC_CONFIG_ACTIONS:
                            self.logger.critical("CRITICAL: module=tc_policy "
                                                 "The following action "
                                                 "attribute is invalid: %s",
                                                 action)
                            sys.exit("Exiting nmeta. Please fix error in "
                                     "tc_policy.yaml file")

    def _validate_conditions(self, policy_conditions):
        """
        Check Traffic Classification (TC) conditions stanza to ensure
        that it is in the correct format so that it won't cause unexpected
        errors during packet checks. Can recurse for nested policy conditions.
        """
        #*** Use this to check if there is a match_type in stanza. Note can't
        #*** check for more than one occurrence as dictionary will just 
        #*** keep attribute and overwrite value. Also note that recursive
        #*** instances use same variable due to scoping:
        self.has_match_type = 0
        #*** Check conditions are valid:
        for policy_condition in policy_conditions.keys():
            #*** Check policy condition attribute is valid:
            if not (policy_condition in TC_CONFIG_CONDITIONS or 
                     policy_condition[0:10] == 'conditions'):
                self.logger.critical("CRITICAL: module=tc_policy "
                "The following PolicyCondition attribute is "
                "invalid: %s", policy_condition)
                sys.exit("Exiting nmeta. Please fix error in "
                         "tc_policy.yaml file")
            #*** Check policy condition value is valid:
            if not policy_condition[0:10] == 'conditions':
                pc_value_type = TC_CONFIG_CONDITIONS[policy_condition]
            else:
                pc_value_type = policy_condition
            pc_value = policy_conditions[policy_condition]
            if pc_value_type == 'String':
                #*** Can't think of a way it couldn't be a valid
                #*** string???
                pass
            elif pc_value_type == 'PortNumber':
                #*** Check is int 0 < x < 65536:
                if not \
                     self.static.is_valid_transport_port(pc_value):
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
            elif pc_value_type == 'MACAddress':
                #*** Check is valid MAC address:
                if not self.static.is_valid_macaddress(pc_value):
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
            elif pc_value_type == 'EtherType':
                #*** Check is valid EtherType - must be two bytes
                #*** as Hex (i.e. 0x0800 is IPv4):
                if not self.static.is_valid_ethertype(pc_value):
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
            elif pc_value_type == 'IPAddressSpace':
                #*** Check is valid IP address, IPv4 or IPv6, can
                #*** include range or CIDR mask:
                if not self.static.is_valid_ip_space(pc_value):
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
            elif pc_value_type == 'MatchType':
                #*** Check is valid match type:
                if not pc_value in TC_CONFIG_MATCH_TYPES:
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
                else:
                    #*** Flag that we've seen a match_type so all is good:
                    self.has_match_type = 1
            elif pc_value_type[0:10] == 'conditions':
                #*** Check value is dictionary:
                if not isinstance(pc_value, dict):
                    self.logger.critical("CRITICAL: "
                          "module=tc_policy A conditions clause"
                          "specified but is invalid: %s "
                          "as %s", policy_condition, pc_value)
                    sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
                #*** Now, do recursive call to validate nested conditions:
                self.logger.debug("DEBUG: module=tc_policy Recursing on "
                                    "nested conditions %s", pc_value)
                self._validate_conditions(pc_value)
            else:
                #*** Whoops! We have a data type in the policy
                #*** that we've forgot to code a check for...
                self.logger.critical("CRITICAL: "
                          "module=tc_policy The following "
                          "PolicyCondition value does not have "
                          "a check: %s, %s", policy_condition, pc_value)
                sys.exit("Exiting nmeta. Coding error "
                                        "in tc_policy.yaml file")
        #*** Check match_type attribute present:
        if not self.has_match_type == 1:
            #*** No match_type attribute in stanza:
            self.logger.critical("CRITICAL: "
                    "module=tc_policy Missing match_type attribute"
                     " in stanza: %s ", policy_conditions)
            sys.exit("Exiting nmeta. Please fix error "
                                        "in tc_policy.yaml file")
        else:
            #*** Reset to zero as otherwise can break parent evaluations:
            self.has_match_type = 0

    def check_policy(self, pkt, dpid, inport):
        """
        Passed a packet-in packet, a Data Path ID (dpid) and an in port.
        Check if packet matches against any policy
        rules and if it does return the associated actions.
        This function is written for efficiency as it will be called for
        every packet-in event and delays will slow down the transmission
        of these packets. For efficiency, it assumes that the TC policy
        is valid as it has been checked after ingestion or update.
        It performs an additional function of sending any packets that
        contain identity information (i.e. LLDP) to the Identity module
        """
        #*** Check to see if it is an LLDP packet
        #*** and if so pass to the identity module to process:
        pkt_eth = pkt.get_protocol(ethernet.ethernet)
        if pkt_eth.ethertype == 35020:
            self.identity.lldp_in(pkt, dpid, inport)
        #*** Check to see if it is an IPv4 packet
        #*** and if so pass to the identity module to process:
        pkt_ip4 = pkt.get_protocol(ipv4.ipv4)
        if pkt_ip4:
            self.identity.ip4_in(pkt)
        #*** Check against TC policy:
        for policy_rule in self._tc_policy.keys():
            _result_dict = self._check_conditions(pkt,
                    self._tc_policy[policy_rule]['conditions'])
            if _result_dict["match"]:
                self.logger.debug("DEBUG: module=tc_policy Matched policy "
                                  "condition(s), returning "
                                  "continue_to_inspect and actions...")
                #*** Merge actions dictionaries. Do type inspection.
                #*** There has to be a better way...!!!
                if (isinstance(self._tc_policy[policy_rule]['actions'], dict)
                         and isinstance(_result_dict['actions'], dict)):
                    _merged_actions = dict(self._tc_policy[policy_rule] \
                        ['actions'].items() + _result_dict['actions'].items())
                elif isinstance(self._tc_policy[policy_rule]['actions'], dict):
                    _merged_actions = self._tc_policy[policy_rule]['actions']
                elif isinstance(_result_dict['actions'], dict):
                    _merged_actions = _result_dict['actions']
                else:
                    _merged_actions = False
                _result_dict['actions'] = _merged_actions
                self.logger.debug("DEBUG: module=tc_policy returning dict %s",
                                  _result_dict)
                return _result_dict
        #*** No hits so return false on everything:
        _result_dict = {'match':False, 'continue_to_inspect':False,
                    'actions': False}
        return _result_dict

    def _check_conditions(self, pkt, conditions):
        """
        Passed a packet-in packet and a conditions stanza (which may contain
        nested conditions stanzas).
        Check to see if packet matches conditions as per the
        match type, and if so return in the dictionary attribute "match" with
        the boolean value True otherwise boolean False.
        The returned dictionary can also contain values indicating
        whether or not a flow should be installed to the switch
        (attribute "continue_to_inspect") and actions
        (attribute "actions")
        A match_type of 'any' will return true as soon as a valid
        match is made and false if end of matching is reached.
        A match_type of 'all' will return false as soon as an invalid
        match is made and true if end of matching is reached.
        """
        #*** initial settings for results dictionary:
        _result_dict = {'match':True, 'continue_to_inspect':False,
                    'actions': False}
        self.match_type = conditions['match_type']
        #*** Loop through conditions checking match:
        for policy_attr in conditions.keys():
            policy_value = conditions[policy_attr]
            #*** Policy Attribute Type is for non-static classifiers to
            #*** hold the attribute prefix (i.e. identity).
            #*** Exclude nested conditions dictionaries from this check:
            if policy_attr[0:10] == 'conditions':
                policy_attr_type = "conditions"
            else:
                policy_attr_type = policy_attr.split("_")
                policy_attr_type = policy_attr_type[0]
            _match = False
            #*** Main if/elif/else check on condition attribute type:
            if policy_attr_type == "identity":
                _match = self.identity.check_identity(policy_attr, 
                                             policy_value, pkt)
            elif policy_attr_type == "payload":
                _payload_dict = self.payload.check_payload(policy_attr,
                                         policy_value, pkt)
                if _payload_dict["match"]:
                        _match = True
                        _result_dict["continue_to_inspect"] = \
                                     _payload_dict["continue_to_inspect"]
            elif policy_attr_type == "conditions":
                #*** Do a recursive call on nested conditions:
                _nested_dict = self._check_conditions(pkt, policy_value)
                _match = _nested_dict["match"]
                #*** TBD: How do we deal with nested continue to inspect
                #***  results that conflict?
                _result_dict["continue_to_inspect"] = \
                                    _nested_dict["continue_to_inspect"]
            elif policy_attr == "match_type":
                #*** Nothing to do:
                pass
            else:
                #*** default to doing a Static Classification match:
                _match = self.static.check_static(policy_attr,
                                                        policy_value, pkt)
            #*** Decide what to do based on match result and match type:
            if _match and self.match_type == "any":
                _result_dict["match"] = True
                return _result_dict
            elif not _match and self.match_type == "all":
                _result_dict["match"] = False
                return _result_dict
            else:
                #*** Not a condition that we take action on so keep going:
                pass
        #*** We've finished loop through all conditions and haven't returned.
        #***  Work out what action to take:
        if not _match and self.match_type == "any":
            _result_dict["match"] = False
            return _result_dict
        elif _match and self.match_type == "all":
            _result_dict["match"] = True
            return _result_dict
        else:
            #*** Unexpected result:
            self.logger.error("ERROR: module=tc_policy Unexpected result at "
                "end of loop through attributes. policy_attr=%s, _match=%s, "
                "self.match_type=%s", policy_attr, _match, self.match_type)
            _result_dict["match"] = False
            return _result_dict

