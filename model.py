import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, logging


logging.set_verbosity_error()


class BertMetaLearning(nn.Module):
    def __init__(self, args):
        super(BertMetaLearning, self).__init__()
        self.args = args
        self.device = None

        self.model = AutoModel.from_pretrained(
            args.model_name, local_files_only=args.local_model
        )

        # Question Answering
        self.qa_outputs = nn.Linear(args.hidden_dims, args.qa_labels)

        # Sequence Classification
        self.sc_dropout = nn.Dropout(args.dropout)
        self.sc_classifier = nn.Linear(args.hidden_dims, args.sc_labels)

    def forward(self, task, data):

        if "qa" in task:

            data["input_ids"] = data["input_ids"].to(self.device)
            data["attention_mask"] = data["attention_mask"].to(self.device)
            data["token_type_ids"] = data["token_type_ids"].to(self.device)

            outputs = self.model(
                data["input_ids"],
                attention_mask=data["attention_mask"],
                token_type_ids=data["token_type_ids"].long(),
            )

            sequence_output = outputs[0]

            logits = self.qa_outputs(sequence_output)
            start_logits, end_logits = logits.split(1, dim=-1)
            start_logits = start_logits.squeeze(-1)
            end_logits = end_logits.squeeze(-1)
            outputs = (start_logits, end_logits,) + outputs[2:]

            if data["answer_start"] is not None and data["answer_end"] is not None:
                data["answer_start"] = data["answer_start"].to(self.device)
                data["answer_end"] = data["answer_end"].to(self.device)
                ignored_index = start_logits.size(1)
                data["answer_start"].clamp_(0, ignored_index)
                data["answer_end"].clamp_(0, ignored_index)
                start_loss = F.cross_entropy(
                    start_logits,
                    data["answer_start"],
                    ignore_index=ignored_index,
                    reduction="none",
                )
                end_loss = F.cross_entropy(
                    end_logits,
                    data["answer_end"],
                    ignore_index=ignored_index,
                    reduction="none",
                )
                loss = (start_loss + end_loss) / 2
                outputs = (loss,) + outputs

        elif "sc" in task:
            data["input_ids"] = data["input_ids"].to(self.device)
            data["attention_mask"] = data["attention_mask"].to(self.device)
            data["token_type_ids"] = data["token_type_ids"].to(self.device)
            data["label"] = data["label"].to(self.device)

            outputs = self.model(
                data["input_ids"],
                attention_mask=data["attention_mask"],
                token_type_ids=data["token_type_ids"].long(),
            )

            pooled_output = outputs[1]

            pooled_output = self.sc_dropout(pooled_output)
            logits = self.sc_classifier(pooled_output)

            loss = F.cross_entropy(logits, data["label"], reduction="none")
            outputs = (loss, logits) + outputs[2:]

        return outputs

    def to(self, *args, **kwargs):
        self = super().to(*args, **kwargs)
        self.device = args[0]  # store device
        self.model = self.model.to(*args, **kwargs)
        self.qa_outputs = self.qa_outputs.to(*args, **kwargs)
        self.sc_dropout = self.sc_dropout.to(*args, **kwargs)
        self.sc_classifier = self.sc_classifier.to(*args, **kwargs)
        return self

