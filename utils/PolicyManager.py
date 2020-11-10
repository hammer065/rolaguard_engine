import os
import pika
import json
import time
import logging as log
from threading import Thread
from db.Models import Policy



class PolicyManager():
    def __init__(self):
        self.policies = { p.id : p for p in self.getPoliciesAndDataCollectors() }
        self.active_policy = None
        self.active_dc_id = None
        self.block_policy_loading = False

    def use_policy(self, organization_id, data_collector_id):
        if self.active_policy and (self.active_policy.organization_id == organization_id or self.active_policy.organization_id is None) and self.active_dc_id == data_collector_id:
          return

        try:
            self.block_policy_loading = True
            for policy in self.policies.values():
                if policy.organization_id == organization_id or policy.organization_id is None and data_collector_id in policy.data_collector_ids:
                    self.active_policy = policy
                    self.active_dc_id = data_collector_id
                    break
            self.block_policy_loading = False
        except Exception as exc:
            log.error(f"Error trying to change the active policy: {exc}")


    def is_enabled(self, alert_type):
        try:
            for item in self.active_policy.items:
                if item.alert_type_code == alert_type:
                    return item.enabled
            return True
        except Exception as exc:
            log.error(f"Error on is_enabled for alert {alert_type}. Exception: {exc}")
            return False


    def get_parameters(self, alert_type):
        try:
            for item in self.active_policy.items:
                if item.alert_type_code == alert_type:                    
                    default_parameters = json.loads(item.alert_type.parameters)
                    default_parameters = {par : val['default'] for par, val in default_parameters.items()}
                    parameters = json.loads(item.parameters)
                    parameters = {par : val for par, val in parameters.items()}

                    # Add missing default parameters and update the item if needed
                    needs_update = False
                    for par, val in default_parameters.items():
                        if par not in parameters:
                            needs_update = True
                            parameters[par] = val
                    if needs_update:
                        item.parameters = json.dumps(parameters)
                        item.db_update()

                    return parameters

            # If no item found for this alert_type, add it with default parameters and return them
            return self.active_policy.add_missing_item(alert_type)

        except Exception as exc:
            log.error(f"Error getting parameters of alert {alert_type}. Exception: {exc}")
        return {}


    def subscribe_to_events(self):
        try:
            def connect_to_mq():
                time.sleep(2)
                rabbit_credentials = pika.PlainCredentials(username = os.environ["RABBITMQ_DEFAULT_USER"],
                                                           password = os.environ["RABBITMQ_DEFAULT_PASS"])
                rabbit_parameters = pika.ConnectionParameters(host = os.environ["RABBITMQ_HOST"],
                                                              port = os.environ["RABBITMQ_PORT"],
                                                              credentials = rabbit_credentials)
                connection = pika.BlockingConnection(rabbit_parameters)
                channel = connection.channel()
                channel.exchange_declare(exchange='policies_events', exchange_type='fanout')
                result = channel.queue_declare(queue='', exclusive=True)
                queue_name = result.method.queue
                channel.queue_bind(exchange='policies_events', queue=queue_name)
                channel.basic_consume(on_message_callback=self._handle_events, queue=queue_name, auto_ack=True)
                channel.start_consuming()

            thread = Thread(target = connect_to_mq)
            thread.setDaemon(True)
            thread.start()
        except Exception as exc:
            log.error(f"Error: could not subscribe to policy events. Exception: {exc}")


    def _handle_events(self, ch, method, properties, body):
        try:
            while self.block_policy_loading:
                time.sleep(1)

            event = json.loads(body.decode('utf-8'))
            log.debug(f"New event on policies_events: {event}")
            policy_id = event['data']['id']
            if (event['type'] == 'CREATED') or (event['type'] == 'UPDATED'):
                policy = Policy.find_one(policy_id)
                self.policies[policy_id] = policy
            elif event['type'] == 'DELETED':
                del self.policies[policy_id]
        except Exception as exc:
            log.error(f"Could not handle policy event. Exception: {exc}")
            return

    def getPoliciesAndDataCollectors(self):
        policies = Policy.find()
        for p in policies:
            dcs = []
            for dc in p.data_collectors:
                dcs.append(dc.id)
            p.data_collector_ids = dcs
        return policies


